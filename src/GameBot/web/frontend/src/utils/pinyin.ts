/** 拼音排序工具
 *
 * 使用 Intl.Collator('zh-CN') 对中文字符串进行拼音顺序比较。
 * 浏览器/Node 环境下中文 locale 比较通常按拼音排序，可作为通用排序函数。
 */

const pinyinCollator = new Intl.Collator('zh-CN')

export function pinyinCompare(a: string, b: string): number {
  return pinyinCollator.compare(a || '', b || '')
}

export function sortByPinyin<T>(arr: T[], getter: (item: T) => string): T[] {
  return [...arr].sort((a, b) => pinyinCompare(getter(a), getter(b)))
}
