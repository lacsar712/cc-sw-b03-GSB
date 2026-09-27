<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api.js'

const role = ref(localStorage.getItem('role') || '')
const jobs = ref([])
const history = ref([])
const reasons = ref({})
const err = ref('')
const ok = ref('')
let timer

const canReconsider = computed(() => role.value === 'reader')

async function refresh() {
  if (!localStorage.getItem('tok')) return
  try {
    const [all, hist] = await Promise.all([api('/api/jobs'), api('/api/reconsiderations')])
    jobs.value = all.filter((j) => j.status === 'done')
    history.value = hist
    err.value = ''
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function reconsider(job) {
  err.value = ''
  ok.value = ''
  const reason = (reasons.value[job.id] || '').trim()
  if (!reason) {
    err.value = `请先为 #${job.id} 填写复议理由`
    return
  }
  try {
    await api(`/api/jobs/${job.id}/reconsider`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    })
    reasons.value[job.id] = ''
    ok.value = `#${job.id} ${job.lamp} 已复议回队，等待重新领取`
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
}

onMounted(() => {
  role.value = localStorage.getItem('role') || ''
  refresh()
  timer = setInterval(refresh, 1000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div>
    <h2>复议台</h2>
    <p v-if="err" style="color:#b00020">{{ err }}</p>
    <p v-if="ok" style="color:#1a7f37">{{ ok }}</p>

    <section style="margin:16px 0; padding:12px; border:1px solid #ccc;">
      <h3>可复议任务（已结案）</h3>
      <p v-if="!jobs.length" style="color:#666">暂无已结案任务</p>
      <table v-else border="1" cellpadding="6" style="border-collapse:collapse; width:100%;">
        <thead>
          <tr>
            <th>编号</th><th>灯种</th><th>标称</th><th>实测</th><th>结论</th><th>理由</th>
            <th>已复议次数</th><th>复议理由</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="j in jobs" :key="j.id">
            <td>{{ j.id }}</td>
            <td>{{ j.lamp }}</td>
            <td>{{ j.nominal_nm }}</td>
            <td>{{ j.measured_nm }}</td>
            <td>{{ j.verdict }}</td>
            <td>{{ j.reason }}</td>
            <td>{{ j.reconsider_count }}</td>
            <td>
              <input
                v-model="reasons[j.id]"
                :disabled="!canReconsider"
                :placeholder="canReconsider ? '填写复议理由' : '仅巡检可复议'"
              />
            </td>
            <td>
              <button
                v-if="canReconsider"
                type="button"
                @click="reconsider(j)"
              >复议</button>
              <span v-else style="color:#999">校准员不可复议</span>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section style="margin:16px 0; padding:12px; border:1px solid #ccc;">
      <h3>复议履历</h3>
      <p v-if="!history.length" style="color:#666">暂无复议记录</p>
      <table v-else border="1" cellpadding="6" style="border-collapse:collapse; width:100%;">
        <thead>
          <tr>
            <th>记录</th><th>任务编号</th><th>灯种</th><th>复议理由</th><th>操作人</th><th>复议次数</th><th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="h in history" :key="h.id">
            <td>{{ h.id }}</td>
            <td>{{ h.job_id }}</td>
            <td>{{ h.lamp }}</td>
            <td>{{ h.reason }}</td>
            <td>{{ h.created_by }}</td>
            <td>第 {{ h.count_after }} 次</td>
            <td>{{ h.created_at }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
