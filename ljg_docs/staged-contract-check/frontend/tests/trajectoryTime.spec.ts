import { describe, expect, it } from "vitest"

import { formatDateTime, formatDuration, formatTime } from "../src/utils/trajectoryTime"

describe("trajectoryTime", () => {
  it("把缺失时区标记的 UTC 串按 UTC 解析，而不是当成本地时间", () => {
    // 06:28 UTC 在北京时间应为 14:28；若被当成本地时间就会显示 06:28。
    const withoutZone = "2026-08-26T06:28:59.388518"
    const withZone = "2026-08-26T06:28:59.388518Z"
    expect(formatTime(withoutZone)).toBe(formatTime(withZone))
    expect(formatDateTime(withoutZone)).toBe(formatDateTime(withZone))
    expect(formatTime(withZone)).toBe(
      new Date(withZone).toLocaleTimeString("zh-CN", { hour12: false }),
    )
  })

  it("没有耗时的记录统一显示“未记录”，不输出 null ms", () => {
    expect(formatDuration(undefined)).toBe("未记录")
    expect(formatDuration(null)).toBe("未记录")
    expect(formatDuration(Number.NaN)).toBe("未记录")
    expect(formatDuration(0)).toBe("0 ms")
    expect(formatDuration(999)).toBe("999 ms")
    expect(formatDuration(10190)).toBe("10.19 s")
  })
})
