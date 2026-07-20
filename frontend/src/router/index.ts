import { createRouter, createWebHistory } from "vue-router"

import HealthView from "../views/HealthView.vue"

export default createRouter({
  history: createWebHistory(),
  routes: [{ path: "/", name: "health", component: HealthView }],
})
