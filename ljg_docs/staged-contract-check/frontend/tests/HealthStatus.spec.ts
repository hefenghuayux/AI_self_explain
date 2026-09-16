import { flushPromises, mount } from "@vue/test-utils"
import ElementPlus from "element-plus"
import { afterEach, describe, expect, it, vi } from "vitest"

import HealthStatus from "../src/components/HealthStatus.vue"

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("HealthStatus", () => {
  it("renders the Element Plus success alert after a healthy response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ status: "ok", database: "ok" }),
      }),
    )

    const wrapper = mount(HealthStatus, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(wrapper.text()).toContain("服务运行正常")
    expect(wrapper.find(".el-alert--success").exists()).toBe(true)
  })

  it("shows an explicit error when FastAPI is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Failed to fetch")))

    const wrapper = mount(HealthStatus, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(wrapper.text()).toContain("后端服务连接失败")
    expect(wrapper.text()).toContain("Failed to fetch")
    expect(wrapper.find(".el-alert--error").exists()).toBe(true)
  })
})
