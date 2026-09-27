import os
from datetime import datetime, timedelta, timezone

import psycopg
from jose import JWTError, jwt
from litestar import Litestar, Request, get, post
from litestar.exceptions import HTTPException
from litestar.status_codes import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
)
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
    review_count integer NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reviews (
    id serial PRIMARY KEY,
    job_id integer NOT NULL REFERENCES jobs(id),
    review_reason text NOT NULL,
    reviewed_by text NOT NULL,
    reviewed_at timestamptz NOT NULL,
    prev_verdict text NOT NULL DEFAULT '',
    prev_reason text NOT NULL DEFAULT '',
    new_verdict text NOT NULL DEFAULT '',
    new_reason text NOT NULL DEFAULT '',
    concluded_at timestamptz
);
"""

# 旧库补列：jobs 新增复议次数
MIGRATIONS = (
    """
    ALTER TABLE jobs ADD COLUMN IF NOT EXISTS review_count integer NOT NULL DEFAULT 0
    """,
)

JOB_COLUMNS = (
    "id, lamp, nominal_nm, measured_nm, status, verdict, reason, created_by, review_count"
)


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


class LoginIn(BaseModel):
    username: str
    password: str


class JobIn(BaseModel):
    lamp: str
    nominal_nm: float
    measured_nm: float


class ReviewIn(BaseModel):
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
            f"SELECT {JOB_COLUMNS} FROM jobs ORDER BY id DESC"
        ).fetchall()
        return list(rows)


@get("/api/reviewable")
async def list_reviewable(request: Request) -> list:
    """复议台：仅已结案行可复议。"""
    user_from_request(request)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT {JOB_COLUMNS} FROM jobs WHERE status='done' ORDER BY id DESC"
        ).fetchall()
        return list(rows)


@get("/api/jobs/{job_id:int}")
async def get_job(request: Request, job_id: int) -> dict:
    user_from_request(request)
    with connect() as conn:
        row = conn.execute(
            f"SELECT {JOB_COLUMNS} FROM jobs WHERE id = %s",
            (job_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="任务不存在")
        return dict(row)


@get("/api/jobs/{job_id:int}/reviews")
async def list_reviews(request: Request, job_id: int) -> list:
    user_from_request(request)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, job_id, review_reason, reviewed_by, reviewed_at,
                   prev_verdict, prev_reason, new_verdict, new_reason, concluded_at
            FROM reviews WHERE job_id = %s ORDER BY id
            """,
            (job_id,),
        ).fetchall()
        return list(rows)


@post("/api/jobs/{job_id:int}/reviews")
async def create_review(request: Request, job_id: int, data: ReviewIn) -> dict:
    """巡检（reader）对已结案行填理由复议：回待处理、清空结论与理由、次数加一。"""
    user = user_from_request(request)
    if user["role"] != "reader":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅巡检可复议")
    reason = data.reason.strip()
    if not reason:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="请填写复议理由")
    with connect() as conn:
        with conn.transaction():
            row = conn.execute(
                "SELECT status, verdict, reason FROM jobs WHERE id = %s FOR UPDATE",
                (job_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="任务不存在")
            if row["status"] != "done":
                raise HTTPException(status_code=HTTP_409_CONFLICT, detail="仅已结案行可复议")
            now = datetime.now(timezone.utc)
            conn.execute(
                """
                INSERT INTO reviews(job_id, review_reason, reviewed_by, reviewed_at,
                                    prev_verdict, prev_reason)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    job_id,
                    reason,
                    user["username"],
                    now,
                    row["verdict"],
                    row["reason"],
                ),
            )
            conn.execute(
                """
                UPDATE jobs
                SET status='pending', verdict='', reason='',
                    review_count = review_count + 1
                WHERE id = %s
                """,
                (job_id,),
            )
        conn.commit()
    return {"id": job_id, "status": "pending", "reviewed_at": now.isoformat()}


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


def on_startup() -> None:
    with connect() as conn:
        conn.execute(SCHEMA)
        for stmt in MIGRATIONS:
            conn.execute(stmt)
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
    route_handlers=[
        health,
        login,
        list_jobs,
        list_reviewable,
        get_job,
        list_reviews,
        create_job,
        create_review,
    ],
    on_startup=[on_startup],
)
