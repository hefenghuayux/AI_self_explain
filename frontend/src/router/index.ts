import { createRouter, createWebHistory, START_LOCATION } from "vue-router"

import { authUser, initializeAuth } from "../stores/auth"
import { fetchSessionHistory } from "../api/sessions"
import LoginView from "../views/LoginView.vue"
import QuestionDetailView from "../views/QuestionDetailView.vue"
import QuestionFormView from "../views/QuestionFormView.vue"
import QuestionListView from "../views/QuestionListView.vue"
import RegisterView from "../views/RegisterView.vue"
import SessionEventLogView from "../views/SessionEventLogView.vue"
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
    { path: "/sessions/:sessionId/logs", name: "session-logs", component: SessionEventLogView, meta: { teacherOnly: true } },
  ],
})

router.beforeEach(async (to, from) => {
  if (to.meta.public) return true
  const authenticated = await initializeAuth()
  if (!authenticated) return { name: "login", query: { redirect: to.fullPath } }
  if (
    to.name === "question-list"
    && (from === START_LOCATION || from.name === "login")
  ) {
    const history = await fetchSessionHistory()
    if (history.length > 0) {
      return { name: "session", params: { sessionId: history[0].id } }
    }
  }
  if (to.meta.teacherOnly && authUser.value?.role !== "TEACHER") {
    return { name: "question-list" }
  }
  return true
})

export default router
