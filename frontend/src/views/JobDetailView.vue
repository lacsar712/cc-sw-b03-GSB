<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api.js'

const route = useRoute()
const router = useRouter()
const job = ref(null)
const reviews = ref([])
const err = ref('')
let timer

async function load() {
  err.value = ''
  job.value = null
  try {
    const [j, rs] = await Promise.all([
      api(`/api/jobs/${route.params.id}`),
      api(`/api/jobs/${route.params.id}/reviews`),
    ])
    job.value = j
    reviews.value = rs
  } catch (e) {
    err.value = String(e.message || e)
  }
}

function fmt(ts) {
  return ts ? new Date(ts).toLocaleString() : ''
}

onMounted(() => {
  load()
  timer = setInterval(load, 1000)
})
onUnmounted(() => clearInterval(timer))
watch(() => route.params.id, load)
</script>

<template>
  <div>
    <p>
      <button type="button" @click="router.push('/')">返回总览</button>
    </p>
    <p v-if="err" style="color:#b00020">{{ err }}</p>
    <section v-if="job" style="margin:16px 0; padding:12px; border:1px solid #ccc;">
      <h3>任务详情 #{{ job.id }}</h3>
      <p>灯种：{{ job.lamp }}</p>
      <p>标称 nm：{{ job.nominal_nm }}</p>
      <p>实测 nm：{{ job.measured_nm }}</p>
      <p>状态：{{ job.status }}</p>
      <p>结论：{{ job.verdict }}</p>
      <p>理由：{{ job.reason }}</p>
      <p>复议次数：{{ job.review_count }}</p>
    </section>

    <section v-if="job" style="margin:16px 0; padding:12px; border:1px solid #ccc;">
      <h3>复议履历</h3>
      <p v-if="reviews.length === 0" class="hint">暂无复议记录</p>
      <table v-else border="1" cellpadding="6" style="border-collapse:collapse; width:100%;">
        <thead>
          <tr>
            <th>#</th><th>复议理由</th><th>复议人</th><th>复议时间</th>
            <th>原结论</th><th>重写结论</th><th>重写理由</th><th>结案时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(r, i) in reviews" :key="r.id">
            <td>{{ i + 1 }}</td>
            <td>{{ r.review_reason }}</td>
            <td>{{ r.reviewed_by }}</td>
            <td>{{ fmt(r.reviewed_at) }}</td>
            <td>{{ r.prev_verdict }}：{{ r.prev_reason }}</td>
            <td>
              <span v-if="r.new_verdict">{{ r.new_verdict }}</span>
              <span v-else class="hint">待重新仲裁</span>
            </td>
            <td>
              <span v-if="r.new_reason">{{ r.new_reason }}</span>
              <span v-else class="hint">—</span>
            </td>
            <td>{{ r.concluded_at ? fmt(r.concluded_at) : '—' }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.hint {
  color: #888;
}
</style>
