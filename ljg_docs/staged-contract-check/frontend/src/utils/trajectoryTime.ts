/**
 * 时间显示统一入口。
 *
 * 后端历史版本会输出不带时区标记的 UTC 时间串（SQLite 读回时丢时区），
 * 而 JS 的 new Date() 会把这种串当成本地时间解析，导致显示整体偏移一个时区。
 * 这里对缺失时区标记的串显式补 Z，避免同一种缺陷再次出现。
 */
function toDate(value: string): Date {
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value)
  return new Date(hasZone ? value : `${value}Z`)
}

export function formatDateTime(value: string): string {
  return toDate(value).toLocaleString("zh-CN", { hour12: false })
}

export function formatTime(value: string): string {
  return toDate(value).toLocaleTimeString("zh-CN", { hour12: false })
}

/** 只有 model.responded / model.failed 记录了耗时；其余记录明确显示“未记录”。 */
export function formatDuration(milliseconds: number | null | undefined): string {
  if (typeof milliseconds !== "number" || !Number.isFinite(milliseconds)) return "未记录"
  if (milliseconds < 1000) return `${milliseconds} ms`
  return `${(milliseconds / 1000).toFixed(2)} s`
}
