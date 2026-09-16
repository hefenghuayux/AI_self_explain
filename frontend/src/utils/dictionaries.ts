/**
 * 学段、学科编码 -> 中文名映射。
 * 权威来源：原系统数据库 tbox_test.sys_dict 字典表（GRADE_PERIOD / SUBJECT）。
 * 未知编码回退为原始值，不做猜测。
 */

export const GRADE_PERIOD_NAMES: Readonly<Record<number, string>> = {
  1: "小学",
  2: "初中",
  3: "高中",
}

export const SUBJECT_NAMES: Readonly<Record<string, string>> = {
  Y: "语文",
  S: "数学",
  E: "英语",
  W: "物理",
  H: "化学",
  C: "生物",
  D: "地理",
  L: "历史",
  Z: "政治",
  K: "科学",
  Q: "其它",
}

export function gradePeriodName(gradePeriod: number | null | undefined): string {
  if (gradePeriod === null || gradePeriod === undefined) {
    return ""
  }
  return GRADE_PERIOD_NAMES[gradePeriod] ?? String(gradePeriod)
}

export function subjectName(subject: string | null | undefined): string {
  if (!subject) {
    return ""
  }
  return SUBJECT_NAMES[subject] ?? subject
}
