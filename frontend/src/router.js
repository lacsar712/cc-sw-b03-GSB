import { createRouter, createWebHistory } from 'vue-router'
import HomeView from './views/HomeView.vue'
import JobDetailView from './views/JobDetailView.vue'
import ReconsiderView from './views/ReconsiderView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/jobs/:id', name: 'job-detail', component: JobDetailView, props: true },
    { path: '/reconsider', name: 'reconsider', component: ReconsiderView },
  ],
})

export default router
