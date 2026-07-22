import { createRouter, createWebHistory } from "vue-router"

import { authUser, initializeAuth } from "../stores/auth"
import LoginView from "../views/LoginView.vue"
import QuestionDetailView from "../views/QuestionDetailView.vue"
import QuestionFormView from "../views/QuestionFormView.vue"
import QuestionListView from "../views/QuestionListView.vue"
import RegisterView from "../views/RegisterView.vue"
import SessionView from "../views/SessionView.vue"

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", name: "login", component: LoginView, meta: { public: true } },
    { path: "/register", name: "register", component: RegisterView, meta: { public: true } },
    { path: "/", name: "question-list", component: QuestionListView },
    { path: "/questions", redirect: "/" },
    { path: "/questions/new", name: "question-create", component: QuestionFormView, meta: { teacherOnly: true } },
    {
      path: "/questions/:questionId/edit",
      name: "question-edit",
      component: QuestionFormView,
      meta: { teacherOnly: true },
    },
    { path: "/questions/:questionId", name: "question-detail", component: QuestionDetailView, meta: { teacherOnly: true } },
    { path: "/sessions/:sessionId", name: "session", component: SessionView },
  ],
})

router.beforeEach(async (to) => {
  if (to.meta.public) return true
  const authenticated = await initializeAuth()
  if (!authenticated) return { name: "login", query: { redirect: to.fullPath } }
  if (to.meta.teacherOnly && authUser.value?.role !== "TEACHER") {
    return { name: "question-list" }
  }
  return true
})

export default router
