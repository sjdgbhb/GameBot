"""圣痕面板 OCR 文本解析 — 单元测试。

覆盖：
- _parse_stigmata_text：各种 OCR 文本格式的解析（标准/混排/缺失/空文本）
- _pick_upgrade_target：未达上限词条选择逻辑
- _update_float_lines：浮窗多行文本格式化（从任务配置读取缩写映射）
"""
import sys
import types
import unittest

# Mock win32com 等大漠依赖（3.12 环境不可用），避免导入链报错
for mod_name in ("win32com", "win32com.client", "pythoncom", "pywintypes"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

from GameBot.runner.tasks.war3.jiubing2.others.upgrade_stigmata import UpgradeStigmataTask


# 与 jiubing2.toml 中 stigmata.term_limit 保持一致
TERM_LIMIT = {
    "生命值": 350, "魔法值": 350, "暴击伤害": 50,
    "物理防御": 40, "魔法抗性": 40, "力量": 40,
    "自然属性": 2, "格挡属性": 5, "穿透属性": 2, "暴击几率": 5,
}

# 与 upgrade_stigmata.toml 中 term_short / pos_labels 保持一致
TERM_SHORT = {
    "生命值": "生命", "魔法值": "魔法", "暴击伤害": "暴伤",
    "物理防御": "物防", "魔法抗性": "魔抗", "力量": "力量",
    "自然属性": "自然", "格挡属性": "格挡", "穿透属性": "穿透",
    "暴击几率": "暴击",
}

POS_LABELS = {"upper": "上位", "core": "核心", "middle": "中位", "lower": "下位"}


class TestParseStigmataText(unittest.TestCase):
    """测试 _parse_stigmata_text 静态方法。"""

    def test_standard_format(self):
        """标准格式：每个位置一行，词条名后紧跟数字。"""
        text = "上位圣痕生命值350魔法值200暴击伤害30核心圣痕物理防御20魔法抗性15力量10中位圣痕自然属性1格挡属性3穿透属性0下位圣痕暴击几率2"
        result = UpgradeStigmataTask._parse_stigmata_text(text, TERM_LIMIT)
        self.assertEqual(result["upper"], [("生命值", 350.0), ("魔法值", 200.0), ("暴击伤害", 30.0)])
        self.assertEqual(result["core"], [("物理防御", 20.0), ("魔法抗性", 15.0), ("力量", 10.0)])
        self.assertEqual(result["middle"], [("自然属性", 1.0), ("格挡属性", 3.0), ("穿透属性", 0.0)])
        self.assertEqual(result["lower"], [("暴击几率", 2.0)])

    def test_with_spaces_and_separators(self):
        """带空格和分隔符的格式。"""
        text = "上位圣痕 生命值 350 魔法值 200 暴击伤害 30 核心圣痕 物理防御 20 魔法抗性 15 力量 10"
        result = UpgradeStigmataTask._parse_stigmata_text(text, TERM_LIMIT)
        self.assertEqual(result["upper"], [("生命值", 350.0), ("魔法值", 200.0), ("暴击伤害", 30.0)])
        self.assertEqual(result["core"], [("物理防御", 20.0), ("魔法抗性", 15.0), ("力量", 10.0)])

    def test_with_colons(self):
        """带冒号的格式：生命值:350。"""
        text = "上位圣痕生命值:350魔法值:200暴击伤害:30核心圣痕物理防御:20魔法抗性:15力量:10"
        result = UpgradeStigmataTask._parse_stigmata_text(text, TERM_LIMIT)
        self.assertEqual(result["upper"], [("生命值", 350.0), ("魔法值", 200.0), ("暴击伤害", 30.0)])
        self.assertEqual(result["core"], [("物理防御", 20.0), ("魔法抗性", 15.0), ("力量", 10.0)])

    def test_multiline_merged(self):
        """多行 OCR 合并后的文本（模拟 ocr_lines 合并）。"""
        text = "上位圣痕生命值350魔法值200暴击伤害30核心圣痕物理防御20魔法抗性15力量10中位圣痕自然属性1格挡属性3穿透属性0下位圣痕暴击几率2"
        result = UpgradeStigmataTask._parse_stigmata_text(text, TERM_LIMIT)
        self.assertIn("upper", result)
        self.assertIn("core", result)
        self.assertIn("middle", result)
        self.assertIn("lower", result)

    def test_ocr_garbled(self):
        """OCR 识别有误：部分数字被识别为字母（如 0→O, 1→l）。
        re.search 会提取第一个有效数字片段，部分识别是合理的。"""
        # "生命值3SO" 中 SO 模拟 OCR 把 50 误识别，但 3 被提取
        text = "上位圣痕生命值3SO魔法值200暴击伤害30"
        result = UpgradeStigmataTask._parse_stigmata_text(text, TERM_LIMIT)
        # 3SO 提取出 3.0（部分识别），其余正常
        self.assertEqual(result["upper"], [("生命值", 3.0), ("魔法值", 200.0), ("暴击伤害", 30.0)])

    def test_empty_text(self):
        """空文本。"""
        result = UpgradeStigmataTask._parse_stigmata_text("", TERM_LIMIT)
        self.assertEqual(result, {})

    def test_no_position_keyword(self):
        """没有位置关键词的文本。"""
        text = "生命值350魔法值200"
        result = UpgradeStigmataTask._parse_stigmata_text(text, TERM_LIMIT)
        self.assertEqual(result, {})

    def test_partial_positions(self):
        """只有部分位置出现。"""
        text = "上位圣痕生命值350魔法值200暴击伤害30中位圣痕自然属性1格挡属性3穿透属性0"
        result = UpgradeStigmataTask._parse_stigmata_text(text, TERM_LIMIT)
        self.assertEqual(result["upper"], [("生命值", 350.0), ("魔法值", 200.0), ("暴击伤害", 30.0)])
        self.assertEqual(result["middle"], [("自然属性", 1.0), ("格挡属性", 3.0), ("穿透属性", 0.0)])
        self.assertNotIn("core", result)
        self.assertNotIn("lower", result)

    def test_decimal_values(self):
        """小数值（如有）。"""
        text = "上位圣痕生命值350.5魔法值200暴击伤害30"
        result = UpgradeStigmataTask._parse_stigmata_text(text, TERM_LIMIT)
        self.assertEqual(result["upper"][0], ("生命值", 350.5))

    def test_term_order_preserved(self):
        """词条顺序与文本中出现顺序一致（对应技能格列号）。"""
        text = "上位圣痕暴击伤害30生命值350魔法值200"
        result = UpgradeStigmataTask._parse_stigmata_text(text, TERM_LIMIT)
        # 暴击伤害在文本中先出现，应排在 idx=0
        self.assertEqual(result["upper"][0], ("暴击伤害", 30.0))
        self.assertEqual(result["upper"][1], ("生命值", 350.0))
        self.assertEqual(result["upper"][2], ("魔法值", 200.0))

    def test_stigmata_prefix(self):
        """带'圣痕'前缀的格式：上位圣痕xxx。"""
        text = "上位圣痕生命值350魔法值200暴击伤害30核心圣痕物理防御20魔法抗性15力量10中位圣痕自然属性1格挡属性3穿透属性0下位圣痕暴击几率2"
        result = UpgradeStigmataTask._parse_stigmata_text(text, TERM_LIMIT)
        self.assertEqual(len(result), 4)
        self.assertEqual(len(result["upper"]), 3)
        self.assertEqual(len(result["core"]), 3)
        self.assertEqual(len(result["middle"]), 3)
        self.assertEqual(len(result["lower"]), 1)

    def test_multiline_newline_separated(self):
        """多行 OCR 文本用换行符分隔，跨行数字不应拼接。

        回归测试：上位行末尾"自然属性+1"与 core 行开头"2核心"
        在无分隔符拼接时会被误读为"自然属性+12"。
        """
        text = (
            "上位圣痕魔法值+338：魔法抗性+27：自然属性+1\n"
            "2核心圣痕生命值+301：物理防御+27：穿透属性+2\n"
            "中位圣痕生命值+317；物理防御+29；穿透属性+1\n"
            "下位圣痕魔法值+328：魔法抗性+31；自然属性+1"
        )
        result = UpgradeStigmataTask._parse_stigmata_text(text, TERM_LIMIT)
        self.assertEqual(result["upper"][2], ("自然属性", 1.0))
        self.assertEqual(result["core"][0], ("生命值", 301.0))


class TestPickUpgradeTarget(unittest.TestCase):
    """测试 _pick_upgrade_target 静态方法。"""

    def test_all_at_limit(self):
        """所有词条已达上限，返回 None。"""
        stats = {
            "upper": [("生命值", 350.0), ("魔法值", 350.0), ("暴击伤害", 50.0)],
            "core": [("物理防御", 40.0), ("魔法抗性", 40.0), ("力量", 40.0)],
            "middle": [("自然属性", 2.0), ("格挡属性", 5.0), ("穿透属性", 2.0)],
            "lower": [("暴击几率", 5.0)],
        }
        self.assertIsNone(UpgradeStigmataTask._pick_upgrade_target(stats, TERM_LIMIT))

    def test_pick_largest_gap(self):
        """选择差距最大的词条。"""
        stats = {
            "upper": [("生命值", 100.0), ("魔法值", 350.0), ("暴击伤害", 50.0)],
            "core": [("物理防御", 40.0), ("魔法抗性", 40.0), ("力量", 40.0)],
            "middle": [("自然属性", 2.0), ("格挡属性", 5.0), ("穿透属性", 2.0)],
            "lower": [("暴击几率", 5.0)],
        }
        # 生命值差距 350-100=250，最大
        target = UpgradeStigmataTask._pick_upgrade_target(stats, TERM_LIMIT)
        self.assertIsNotNone(target)
        pos, idx, name, current, limit = target
        self.assertEqual(pos, "upper")
        self.assertEqual(idx, 0)
        self.assertEqual(name, "生命值")
        self.assertEqual(current, 100.0)
        self.assertEqual(limit, 350.0)

    def test_partial_stats(self):
        """只有部分位置数据时，仍能选择未达上限的词条。"""
        stats = {
            "upper": [("生命值", 50.0), ("魔法值", 200.0), ("暴击伤害", 30.0)],
        }
        target = UpgradeStigmataTask._pick_upgrade_target(stats, TERM_LIMIT)
        self.assertIsNotNone(target)
        pos, idx, name, current, limit = target
        self.assertEqual(pos, "upper")
        self.assertEqual(name, "生命值")
        self.assertEqual(current, 50.0)

    def test_empty_stats(self):
        """空数据，返回 None。"""
        self.assertIsNone(UpgradeStigmataTask._pick_upgrade_target({}, TERM_LIMIT))

    def test_exceeds_limit(self):
        """超过上限的词条不被选中（current >= limit）。"""
        stats = {
            "upper": [("生命值", 400.0), ("魔法值", 350.0), ("暴击伤害", 50.0)],
            "core": [("物理防御", 40.0), ("魔法抗性", 40.0), ("力量", 40.0)],
            "middle": [("自然属性", 2.0), ("格挡属性", 5.0), ("穿透属性", 2.0)],
            "lower": [("暴击几率", 5.0)],
        }
        # 生命值 400 > 350，其他都达上限，应返回 None
        self.assertIsNone(UpgradeStigmataTask._pick_upgrade_target(stats, TERM_LIMIT))


class TestUpdateFloatLines(unittest.TestCase):
    """测试 _update_float_lines 方法（浮窗多行文本格式化）。"""

    def _make_task(self):
        """构造一个带最小配置的 mock 任务实例。"""
        task = UpgradeStigmataTask.__new__(UpgradeStigmataTask)
        task.upgrade_cfg = {"term_short": TERM_SHORT, "pos_labels": POS_LABELS}
        return task

    def test_full_stats(self):
        """四个位置都有数据时，输出四行格式化文本。"""
        task = self._make_task()
        captured = []
        task._progress_lines = lambda lines: captured.append(lines)
        stats = {
            "upper": [("魔法值", 338.0), ("魔法抗性", 27.0), ("自然属性", 1.0)],
            "core": [("生命值", 301.0), ("物理防御", 27.0), ("穿透属性", 2.0)],
            "middle": [("生命值", 317.0), ("物理防御", 29.0), ("穿透属性", 1.0)],
            "lower": [("魔法值", 328.0), ("魔法抗性", 31.0), ("自然属性", 1.0)],
        }
        task._update_float_lines(stats, TERM_LIMIT)
        self.assertEqual(len(captured), 1)
        lines = captured[0]
        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[0], "上位: 魔法338/350 魔抗27/40 自然1/2")
        self.assertEqual(lines[1], "核心: 生命301/350 物防27/40 穿透2/2")
        self.assertEqual(lines[2], "中位: 生命317/350 物防29/40 穿透1/2")
        self.assertEqual(lines[3], "下位: 魔法328/350 魔抗31/40 自然1/2")

    def test_partial_stats(self):
        """只有部分位置有数据时，仅输出有数据的位置行。"""
        task = self._make_task()
        captured = []
        task._progress_lines = lambda lines: captured.append(lines)
        stats = {
            "upper": [("生命值", 100.0), ("魔法值", 200.0), ("暴击伤害", 30.0)],
        }
        task._update_float_lines(stats, TERM_LIMIT)
        lines = captured[0]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0], "上位: 生命100/350 魔法200/350 暴伤30/50")

    def test_no_callback(self):
        """未设置 _progress_lines 时不报错。"""
        task = self._make_task()
        task._progress_lines = None
        # 不应抛异常
        task._update_float_lines({"upper": [("生命值", 100.0)]}, TERM_LIMIT)

    def test_empty_stats(self):
        """空 stats 时输出空列表。"""
        task = self._make_task()
        captured = []
        task._progress_lines = lambda lines: captured.append(lines)
        task._update_float_lines({}, TERM_LIMIT)
        self.assertEqual(captured[0], [])

    def test_fallback_without_config(self):
        """upgrade_cfg 中无 term_short/pos_labels 时回退到原始名称。"""
        task = UpgradeStigmataTask.__new__(UpgradeStigmataTask)
        task.upgrade_cfg = {}
        captured = []
        task._progress_lines = lambda lines: captured.append(lines)
        stats = {"upper": [("生命值", 100.0)]}
        task._update_float_lines(stats, TERM_LIMIT)
        lines = captured[0]
        self.assertEqual(lines[0], "upper: 生命值100/350")


if __name__ == "__main__":
    unittest.main()
