import { createRouter, createWebHistory } from "vue-router"

import HealthView from "../views/HealthView.vue"
import QuestionDetailView from "../views/QuestionDetailView.vue"
import QuestionFormView from "../views/QuestionFormView.vue"
import QuestionListView from "../views/QuestionListView.vue"

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "health", component: HealthView },
    { path: "/questions", name: "question-list", component: QuestionListView },
    { path: "/questions/new", name: "question-create", component: QuestionFormView },
    {
      path: "/questions/:questionId/edit",
      name: "question-edit",
      component: QuestionFormView,
    },
    { path: "/questions/:questionId", name: "question-detail", component: QuestionDetailView },
  ],
})
