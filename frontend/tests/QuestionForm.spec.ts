import { flushPromises, mount } from "@vue/test-utils"
import ElementPlus from "element-plus"
import { describe, expect, it } from "vitest"

import QuestionForm from "../src/components/QuestionForm.vue"
import type { QuestionInput } from "../src/types/question"

function questionInput(): QuestionInput {
  return {
    questionContent: "计算 1 + 1。",
    standardAnswer: "2",
    rubricPoints: ["正确计算加法"],
    commonErrors: ["把结果写成 3"],
    alternativeSolutions: ["使用实物计数"],
    layeredHints: ["先数一数两个数"],
    guidedQuestions: ["两个 1 合起来是多少？"],
    fullSolution: "1 加 1 等于 2。",
  }
}

describe("QuestionForm", () => {
  it("submits complete question material", async () => {
    const input = questionInput()
    const wrapper = mount(QuestionForm, {
      props: { initialQuestion: input, submitting: false, serverError: "" },
      global: { plugins: [ElementPlus] },
    })

    await wrapper.get("form").trigger("submit")
    await flushPromises()

    expect(wrapper.emitted("submit")).toEqual([[input]])
  })

  it("rejects duplicate rubric points before requesting the API", async () => {
    const input = questionInput()
    input.rubricPoints = ["正确计算加法", "正确计算加法"]
    const wrapper = mount(QuestionForm, {
      props: { initialQuestion: input, submitting: false, serverError: "" },
      global: { plugins: [ElementPlus] },
    })

    await wrapper.get("form").trigger("submit")
    await flushPromises()

    expect(wrapper.text()).toContain("评分点不能重复")
    expect(wrapper.emitted("submit")).toBeUndefined()
  })
})
