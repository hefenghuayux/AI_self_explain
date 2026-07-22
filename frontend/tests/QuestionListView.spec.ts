import { flushPromises, mount } from "@vue/test-utils"
import ElementPlus from "element-plus"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, describe, expect, it, vi } from "vitest"

import { login } from "../src/stores/auth"
import QuestionListView from "../src/views/QuestionListView.vue"
import type { Question } from "../src/types/question"

function question(): Question {
  return {
    id: 1,
    questionContent: "计算 1 + 1。",
    standardAnswer: "2",
    rubricPoints: ["正确计算加法"],
    commonErrors: ["结果写成 3"],
    alternativeSolutions: ["实物计数"],
    layeredHints: ["先数一数"],
    guidedQuestions: [],
    fullSolution: "1 加 1 等于 2。",
    archivedAt: null,
    createdAt: "2026-07-22T00:00:00Z",
    updatedAt: "2026-07-22T00:00:00Z",
  }
}

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: QuestionListView },
      { path: "/sessions/:sessionId", component: { template: "<div />" } },
      { path: "/questions/new", component: { template: "<div />" } },
      { path: "/questions/:questionId", component: { template: "<div />" } },
      { path: "/questions/:questionId/edit", component: { template: "<div />" } },
    ],
  })
}

afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

describe("QuestionListView", () => {
  it("lets a student start self-explanation without showing management actions", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          token: "student-token",
          expiresAt: "2026-08-22T00:00:00Z",
          user: { id: 1, username: "student", fullName: "学生", role: "STUDENT" },
        }),
      })
      .mockResolvedValueOnce({ ok: true, json: async () => [question()] })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: 99 }) })
    vi.stubGlobal("fetch", fetchMock)
    await login("student", "secret6", false)
    const router = createTestRouter()
    await router.push("/")
    await router.isReady()

    const wrapper = mount(QuestionListView, {
      global: { plugins: [ElementPlus, router] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain("题目列表")
    expect(wrapper.text()).toContain("自讲")
    expect(wrapper.text()).not.toContain("录入题目")
    expect(wrapper.text()).not.toContain("编辑")
    expect(wrapper.text()).not.toContain("归档")

    const selfExplainButton = wrapper.findAll("button").find((item) => item.text() === "自讲")
    await selfExplainButton?.trigger("click")
    await flushPromises()

    expect(router.currentRoute.value.fullPath).toBe("/sessions/99")
  })

  it("shows question management actions to a teacher", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            token: "teacher-token",
            expiresAt: "2026-08-22T00:00:00Z",
            user: { id: 2, username: "teacher", fullName: "教师", role: "TEACHER" },
          }),
        })
        .mockResolvedValueOnce({ ok: true, json: async () => [question()] }),
    )
    await login("teacher", "secret6", false)
    const router = createTestRouter()
    await router.push("/")
    await router.isReady()

    const wrapper = mount(QuestionListView, {
      global: { plugins: [ElementPlus, router] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain("自讲")
    expect(wrapper.text()).toContain("录入题目")
    expect(wrapper.text()).toContain("编辑")
    expect(wrapper.text()).toContain("归档")
  })
})
