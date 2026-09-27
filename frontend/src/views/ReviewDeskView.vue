<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api.js'

const role = ref(localStorage.getItem('role') || '')
const jobs = ref([])
const err = ref('')
const reasons = ref({})
const busyId = ref(0)
let timer

const canReview = () => role.value === 'reader'

async function refresh() {
  if (!localStorage.getItem('tok')) return
  try {
    jobs.value = await api('/api/reviewable')
    err.value = ''
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function review(job) {
  err.value = ''
  const reason = (reasons.value[job.id] || '').trim()
  if (!reason) {
    err.value = `#${job.id} 请填写复议理由`
    return
  }
  busyId.value = job.id
  try {
    await api(`/api/jobs/${job.id}/reviews`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    })
    delete reasons.value[job.id]
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busyId.value = 0
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
    <h3>复议台 · 已结案可复议</h3>
    <p class="hint">仅巡检可将已结案行填理由复议回队；复议后该行回到待处理，结论与理由清空、复议次数加一。</p>
    <p v-if="err" style="color:#b00020">{{ err }}</p>
    <p v-if="!canReview()" class="hint">当前为校准员账号，不可点复议；仅展示已结案行。</p>
    <table border="1" cellpadding="6" style="border-collapse:collapse; width:100%;">
      <thead>
        <tr>
          <th>编号</th><th>灯种</th><th>标称</th><th>实测</th>
          <th>结论</th><th>理由</th><th>已复议</th><th>复议理由</th><th>操作</th>
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
          <td>{{ j.review_count }}</td>
          <td>
            <input
              v-model="reasons[j.id]"
              type="text"
              placeholder="填写复议理由"
              :disabled="!canReview()"
              style="width:180px"
            />
          </td>
          <td>
            <button
              type="button"
              :disabled="!canReview() || busyId === j.id"
              @click="review(j)"
            >复议回队</button>
          </td>
        </tr>
        <tr v-if="jobs.length === 0">
          <td colspan="9" style="text-align:center; color:#666;">暂无可复议行</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.hint {
  color: #666;
  font-size: 13px;
}
</style>
