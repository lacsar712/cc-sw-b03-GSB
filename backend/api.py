import os
from datetime import datetime, timedelta, timezone

import psycopg
from jose import JWTError, jwt
from litestar import Litestar, Request, get, post
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN
from passlib.context import CryptContext
from psycopg.rows import dict_row
from pydantic import BaseModel

DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54395/spectrum")
SECRET = os.environ.get("JWT_SECRET", "spectrum-dev-secret")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
USERS = {
    "calibrator": {"role": "writer", "password_hash": pwd.hash("calib123456")},
    "inspector": {"role": "reader", "password_hash": pwd.hash("insp123456")},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id serial PRIMARY KEY,
    lamp text NOT NULL,
    nominal_nm double precision NOT NULL,
    measured_nm double precision NOT NULL,
    status text NOT NULL,
    verdict text NOT NULL DEFAULT '',
    reason text NOT NULL DEFAULT '',
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    reconsider_count integer NOT NULL DEFAULT 0
);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS reconsider_count integer NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS reconsiderations (
    id serial PRIMARY KEY,
    job_id integer NOT NULL REFERENCES jobs(id),
    reason text NOT NULL,
    created_by text NOT NULL,
    count_after integer NOT NULL,
    created_at timestamptz NOT NULL
);
"""


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


class LoginIn(BaseModel):
    username: str
    password: str


class JobIn(BaseModel):
    lamp: str
    nominal_nm: float
    measured_nm: float


class ReconsiderIn(BaseModel):
    reason: str


def user_from_request(request: Request) -> dict:
    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="未登录")
    try:
        payload = jwt.decode(auth[7:], SECRET, algorithms=["HS256"])
    except JWTError as exc:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="无效令牌") from exc
    if payload.get("sub") not in USERS:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="无效令牌")
    return {"username": payload["sub"], "role": payload.get("role")}


@get("/api/health")
async def health() -> dict:
    return {"status": "ok", "service": "spectrum-wavelength-desk"}


@post("/api/login")
async def login(data: LoginIn) -> dict:
    u = USERS.get(data.username)
    if not u or not pwd.verify(data.password, u["password_hash"]):
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    token = jwt.encode(
        {
            "sub": data.username,
            "role": u["role"],
            "exp": datetime.now(timezone.utc) + timedelta(hours=12),
        },
        SECRET,
        algorithm="HS256",
    )
    return {"access_token": token, "role": u["role"], "username": data.username}


@get("/api/jobs")
async def list_jobs(request: Request) -> list:
    user_from_request(request)
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, lamp, nominal_nm, measured_nm, status, verdict, reason, created_by, reconsider_count FROM jobs ORDER BY id DESC"
        ).fetchall()
        return list(rows)


@get("/api/jobs/{job_id:int}")
async def get_job(request: Request, job_id: int) -> dict:
    user_from_request(request)
    with connect() as conn:
        row = conn.execute(
            "SELECT id, lamp, nominal_nm, measured_nm, status, verdict, reason, created_by, reconsider_count FROM jobs WHERE id = %s",
            (job_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="任务不存在")
        return dict(row)


@post("/api/jobs")
async def create_job(request: Request, data: JobIn) -> dict:
    user = user_from_request(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅校准员可提交")
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO jobs(lamp, nominal_nm, measured_nm, status, verdict, reason, created_by, created_at)
            VALUES (%s,%s,%s,'pending','','',%s,%s) RETURNING id
            """,
            (data.lamp.strip(), data.nominal_nm, data.measured_nm, user["username"], datetime.now(timezone.utc)),
        ).fetchone()
        conn.commit()
        return {"id": row["id"], "status": "pending"}


@post("/api/jobs/{job_id:int}/reconsider")
async def reconsider_job(request: Request, job_id: int, data: ReconsiderIn) -> dict:
    user = user_from_request(request)
    if user["role"] != "reader":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅巡检可复议，校准员不可复议")
    reason = data.reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="请填写复议理由")
    with connect() as conn:
        row = conn.execute("SELECT status FROM jobs WHERE id = %s", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="任务不存在")
        updated = conn.execute(
            """
            UPDATE jobs
            SET status='pending', verdict='', reason='', reconsider_count=reconsider_count+1
            WHERE id=%s AND status='done'
            RETURNING reconsider_count
            """,
            (job_id,),
        ).fetchone()
        if not updated:
            raise HTTPException(status_code=409, detail="仅已结案任务可复议")
        count = updated["reconsider_count"]
        conn.execute(
            """
            INSERT INTO reconsiderations(job_id, reason, created_by, count_after, created_at)
            VALUES (%s,%s,%s,%s,%s)
            """,
            (job_id, reason, user["username"], count, datetime.now(timezone.utc)),
        )
        conn.commit()
        return {"id": job_id, "status": "pending", "reconsider_count": count}


@get("/api/reconsiderations")
async def list_reconsiderations(request: Request) -> list:
    user_from_request(request)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT r.id, r.job_id, j.lamp, r.reason, r.created_by, r.count_after,
                   to_char(r.created_at, 'YYYY-MM-DD HH24:MI:SS') AS created_at
            FROM reconsiderations r
            JOIN jobs j ON j.id = r.job_id
            ORDER BY r.id DESC
            """
        ).fetchall()
        return list(rows)


def on_startup() -> None:
    with connect() as conn:
        conn.execute(SCHEMA)
        n = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
        if n == 0:
            now = datetime.now(timezone.utc)
            conn.execute(
                """
                INSERT INTO jobs(lamp, nominal_nm, measured_nm, status, verdict, reason, created_by, created_at)
                VALUES
                ('氦灯-587', 587.56, 587.50, 'done', '合格', '偏差 0.0600 nm 在允差内', 'seed', %s),
                ('汞灯-546', 546.07, 546.30, 'done', '超差', '偏差 0.2300 nm 超过允差 0.08', 'seed', %s)
                """,
                (now, now),
            )
        conn.commit()


app = Litestar(
    route_handlers=[health, login, list_jobs, get_job, create_job, reconsider_job, list_reconsiderations],
    on_startup=[on_startup],
)
