import { createRouter, createWebHistory } from "vue-router"

import { authUser, initializeAuth } from "../stores/auth"

const LoginView = () => import("../views/LoginView.vue")
const QuestionDetailView = () => import("../views/QuestionDetailView.vue")
const QuestionFormView = () => import("../views/QuestionFormView.vue")
const QuestionListView = () => import("../views/QuestionListView.vue")
const RegisterView = () => import("../views/RegisterView.vue")
const SessionEventLogView = () => import("../views/SessionEventLogView.vue")
const SessionView = () => import("../views/SessionView.vue")
const UserGuideView = () => import("../views/UserGuideView.vue")

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", name: "login", component: LoginView, meta: { public: true } },
    { path: "/register", name: "register", component: RegisterView, meta: { public: true } },
    { path: "/", name: "question-list", component: QuestionListView },
    { path: "/guide", name: "user-guide", component: UserGuideView },
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

router.beforeEach(async (to) => {
  if (to.meta.public) return true
  const authenticated = await initializeAuth()
  if (!authenticated) return { name: "login" }
  if (to.meta.teacherOnly && authUser.value?.role !== "TEACHER") {
    return { name: "question-list" }
  }
  return true
})

export default router
