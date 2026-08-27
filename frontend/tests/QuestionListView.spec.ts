import { flushPromises, mount } from "@vue/test-utils"
import ElementPlus from "element-plus"
import { createMemoryHistory, createRouter } from "vue-router"
import { afterEach, describe, expect, it, vi } from "vitest"

import { login } from "../src/stores/auth"
import QuestionListView from "../src/views/QuestionListView.vue"
import type { QuestionListItem } from "../src/types/question"

function question(): QuestionListItem {
  return {
    id: 1,
    evaluationMode: "FULL_RUBRIC",
    questionContent: '<p>计算 1 + 1。</p><img src="https://example.test/question.png">',
    gradePeriod: 2,
    subject: "S",
    qType: 1,
    difficultyLevel: 1,
    rubricPointCount: 1,
    archivedAt: null,
  }
}

function questionListResponse() {
  return {
    items: [question()],
    pagination: { page: 1, pageSize: 20, total: 1, totalPages: 1 },
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
  it("lets a student start or restart self-explanation without showing management actions", async () => {
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
      .mockResolvedValueOnce({ ok: true, json: async () => ({ gradePeriods: [2], subjects: ["S"] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => questionListResponse() })
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
    expect(wrapper.find('.question-rich-text img').attributes("src")).toBe("https://example.test/question.png")
    expect(wrapper.text()).not.toContain("录入题目")
    expect(wrapper.text()).not.toContain("编辑")
    expect(wrapper.text()).not.toContain("归档")

    const selfExplainButton = wrapper.findAll("button").find((item) => item.text() === "开始自讲")
    await selfExplainButton?.trigger("click")
    await flushPromises()

    expect(router.currentRoute.value.fullPath).toBe("/sessions/99")
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/sessions",
      expect.objectContaining({ body: JSON.stringify({ questionId: 1, restart: false }) }),
    )
    expect(wrapper.text()).toContain("重新自讲")
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
        .mockResolvedValueOnce({ ok: true, json: async () => ({ gradePeriods: [2], subjects: ["S"] }) })
        .mockResolvedValueOnce({ ok: true, json: async () => questionListResponse() }),
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
