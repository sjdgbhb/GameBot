"""
宝箱检测拾取测试 — 与 patrol_loot 任务脚本逻辑一致的独立测试。
检测地面宝箱 → OCR 识别物品名称 → 拾取目标物品，最多 3 轮。

使用方法（大漠脚本环境 .venv-dm）：
  1. 英雄已在游戏内且处于脱战状态
  2. .venv-dm/Scripts/python.exe -m tests.test_chest_detect
  3. 5 秒内切回游戏窗口
  4. Ctrl+C 停止
"""
import os
import tempfile
import time
from typing import Optional

from PIL import Image, ImageDraw

from GameBot.config import config
from GameBot.inference import get_inference_client, get_ocr_client
from GameBot.runner import DmClient
from GameBot.runner.business.war3 import TextMonitor, War3Business
from GameBot.runner.business.war3.jiubing2 import get_inventory_hotkey
from GameBot.utils import logger
from GameBot.utils.exception_handler import setup_global_exception_hook

# 调试截图保存目录
DEBUG_DIR = os.path.join(tempfile.gettempdir(), "chest_debug")


class ChestDetectTest:
    """实时宝箱检测拾取测试。"""

    def __init__(self, cfg: dict):
        self.task_cfg = cfg
        self.cfg = cfg["war3"]["jiubing2"]["tasks"]["others"]["patrol_loot"]
        self.dm = DmClient()

        war3_cfg = self.task_cfg.get("war3", {})
        hero_cfg = self.task_cfg.get("hero", {})

        self.war3 = War3Business(self.dm, war3_cfg)
        self.war3_cfg = war3_cfg
        self.hero_cfg = hero_cfg

        self.chest_cfg = self.task_cfg.get("chest", {})
        self.item_text_cfg = self.task_cfg.get("item_text", {})
        self.pickup_cfg = self.task_cfg.get("pickup", {})
        self.desired_items = self.cfg.get("desired_items", [])
        self.hover_wait_time = self.chest_cfg.get('hover_wait_time', 1.5)
        self.mouse_avoid_pos = self.cfg.get("mouse_avoid_pos", [200, 200])

        # 解析目标物品（支持 {name, count} 格式）
        self.item_targets = self._parse_item_targets(self.desired_items)
        self.storage_full = False

        self.hwnd = None
        self._scan_count = 0

    # ── 主循环 ──────────────────────────────────────────

    def run(self):
        logger.info(f"宝箱检测拾取测试开始，目标物品: {self.desired_items}")
        logger.info("与 patrol_loot 任务脚本逻辑一致，按 Ctrl+C 停止")

        hwnd = self.dm.get_active_window(
            self.war3_cfg["window_class"], self.war3_cfg["window_title"]
        )
        if not hwnd:
            logger.error("未找到 war3 窗口，请先切换到游戏窗口")
            return

        self.hwnd = hwnd
        with self.dm.bind_window(hwnd):
            self.war3.set_client_size(hwnd)
            logger.info("正在初始化推理子进程（OCR + AI 模型）...")
            get_inference_client()
            get_ocr_client()
            logger.info("模型初始化完成")
            monitor = self._make_monitor(hwnd)
            try:
                self._pickup_loop(monitor)
            except KeyboardInterrupt:
                logger.info("用户中断，测试结束")
            finally:
                if monitor is not None:
                    monitor.stop()

        logger.info("宝箱检测拾取测试结束")

    def _make_monitor(self, hwnd: int):
        interval = self.cfg.get("monitor_interval", 0.2)
        monitor = TextMonitor(
            self.war3, self.task_cfg.get("prompt_text"), interval=interval
        )
        monitor.start(hwnd)
        return monitor

    # ── 拾取循环（与 patrol_loot._pickup_loop 一致）──────────

    def _pickup_loop(self, monitor: TextMonitor):
        """循环检测宝箱 → 边识别边拾取 → 再次检测宝箱。

        循环终止条件：本轮未检测到宝箱、或本轮未检测到目标物品、或达到最大检测次数 3 次。
        """
        if self._all_items_satisfied():
            logger.info("所有目标物品已拾取完毕，跳过拾取")
            return

        max_rounds = 3
        for round_idx in range(1, max_rounds + 1):
            chests = self._find_all_chests()
            if not chests:
                logger.info(f"第 {round_idx} 轮检测：未检测到地面宝箱，拾取结束")
                break
            logger.info(f"第 {round_idx} 轮检测：发现 {len(chests)} 个宝箱")
            found_target_this_round = False
            for idx, cx, cy, conf in chests:
                if self.storage_full or self._all_items_satisfied():
                    break
                picked = self._try_pickup_chest(idx, cx, cy, conf, monitor)
                if picked is not None:
                    found_target_this_round = True
                    # 拾取后重置游戏状态：ESC 取消技能瞄准，鼠标移开清 tooltip，等待英雄稳定
                    self.dm.key_press_char('esc')
                    self.dm.move_to(*self.mouse_avoid_pos)
                    time.sleep(self.hover_wait_time)
                if self.storage_full:
                    break

            if self.storage_full or self._all_items_satisfied():
                break
            if not found_target_this_round:
                logger.info(f"第 {round_idx} 轮检测：本轮未检测到目标物品，拾取结束")
                break

        if not self.storage_full:
            self.war3.send_msg(self.task_cfg['command']['clear_nearby'])
            logger.info("已清理地面物品")

    def _try_pickup_chest(self, idx, cx, cy, conf, monitor: TextMonitor) -> Optional[bool]:
        """识别单个宝箱物品并尝试拾取（与 patrol_loot._try_pickup_chest 一致）。

        :return: True=拾取成功(含重试), False=检测到目标但拾取失败, None=非目标/未识别
        """
        self.dm.move_to(cx, cy)
        time.sleep(self.hover_wait_time)
        item_name = self._read_item_name(cx, cy)
        matched_item = self._match_desired(item_name)

        if not (item_name and matched_item):
            logger.info(f"宝箱#{idx} ({cx},{cy}) conf={conf:.2f} → [非目标] {item_name or '(未识别)'} → 跳过")
            return None

        result = self._pickup_one(cx, cy, monitor)
        if result == "storage_full":
            logger.error("储物箱已满，停止测试")
            self.storage_full = True
            return False
        elif result == "unclickable":
            logger.info(f"宝箱#{idx} ({cx},{cy}) conf={conf:.2f} → [目标] {item_name} → 拾取失败：不可点击")
            success = self._handle_unclickable(cx, cy, monitor)
            if success:
                self._mark_picked(matched_item, item_name)
                logger.info(f"宝箱#{idx} ({cx},{cy}) → 重试拾取成功（{self.item_targets[matched_item]['picked']}/{self.item_targets[matched_item]['target']}）")
            else:
                logger.info(f"宝箱#{idx} ({cx},{cy}) → 重试失败，跳过")
            return success
        else:
            self._mark_picked(matched_item, item_name)
            logger.info(f"宝箱#{idx} ({cx},{cy}) conf={conf:.2f} → [目标] {item_name} → 拾取成功（{self.item_targets[matched_item]['picked']}/{self.item_targets[matched_item]['target']}）")
            return True

    def _mark_picked(self, matched_item: str, item_name: str):
        """记录拾取成功：更新目标计数、上报进度。"""
        self.item_targets[matched_item]['picked'] += 1
        self._log_progress()

    # ── 宝箱检测（与 patrol_loot._find_all_chests 一致）──────────

    def _find_all_chests(self):
        """全屏AI检测宝箱，返回 [(index, x, y, confidence), ...]，x/y 为宝箱中心坐标。"""
        self.dm.move_to(*self.mouse_avoid_pos)
        time.sleep(0.1)

        cx, cy, _, _ = self.dm.get_client_rect(self.hwnd)
        client_size = self.war3_cfg.get('client_size', [1902, 1033])
        bbox = [cx, cy, cx + client_size[0], cy + client_size[1]]
        t0 = time.time()
        detections = get_inference_client().capture_and_detect_chests(bbox)
        logger.debug(f"宝箱检测耗时: {time.time() - t0:.3f}s，检测到 {len(detections) if detections else 0} 个")
        if not detections:
            return []

        # 保存带检测框的标注截图供调试
        self._save_annotated_screenshot(cx, cy, client_size, detections)

        results = []
        for i, (x1, y1, x2, y2, confidence) in enumerate(detections):
            cx_pt = (x1 + x2) // 2
            cy_pt = (y1 + y2) // 2
            results.append((i, cx_pt, cy_pt, confidence))
            logger.info(
                f"AI检测宝箱 #{i}: 中心({cx_pt},{cy_pt}) conf={confidence:.2f} box=[{x1},{y1},{x2},{y2}]"
            )
        return results

    def _save_annotated_screenshot(self, cx: int, cy: int, client_size: list, detections: list):
        """保存带检测框的标注截图到调试目录。"""
        os.makedirs(DEBUG_DIR, exist_ok=True)
        tmp_bmp = os.path.join(DEBUG_DIR, f"scan_{self._scan_count}.bmp")
        if not self.dm.capture_region(cx, cy, client_size[0], client_size[1], tmp_bmp):
            logger.debug("调试截图失败，跳过标注")
            return
        img = Image.open(tmp_bmp).convert("RGB")
        annotated = img.copy()
        draw = ImageDraw.Draw(annotated)
        for i, (x1, y1, x2, y2, confidence) in enumerate(detections):
            draw.rectangle([x1, y1, x2, y2], outline="red", width=3)
            draw.text((x1 + 2, y2 + 2), f"#{i} {confidence:.2f}", fill="red")
        path = os.path.join(DEBUG_DIR, f"scan_{self._scan_count}_annotated.png")
        annotated.save(path)
        os.remove(tmp_bmp)
        logger.debug(f"标注截图已保存: {path}")

    # ── 物品名称 OCR ──────────────────────────────────────

    def _read_item_name(self, chest_x: int, chest_y: int) -> str:
        """OCR 读取宝箱上方区域的物品名称（与 patrol_loot._read_item_name 一致）。"""
        offset_y = self.item_text_cfg.get('offset_y', 50)
        half_w = self.item_text_cfg.get('area_width', 200) // 2
        half_h = self.item_text_cfg.get('area_height', 60) // 2

        text_y = chest_y - offset_y
        area_coords = [
            chest_x - half_w, text_y - half_h,
            chest_x + half_w, text_y + half_h,
        ]
        bbox = self.war3._compute_ocr_bbox({"area_coords": area_coords}, self.hwnd)
        text = get_ocr_client().ocr_screen(bbox)
        normalized = self.war3._normalize_ocr(text)
        logger.debug(f"OCR原始: '{text}' → 规范化: '{normalized}'")

        # 保存 OCR 区域截图供调试
        self._save_ocr_region_screenshot(bbox, chest_x, chest_y)

        return normalized

    def _save_ocr_region_screenshot(self, bbox, chest_x: int, chest_y: int):
        """保存 OCR 区域截图到调试目录。"""
        os.makedirs(DEBUG_DIR, exist_ok=True)
        tmp = os.path.join(DEBUG_DIR, f"ocr_{chest_x}_{chest_y}.bmp")
        # 用大漠截取屏幕 bbox 区域
        self.dm.capture_region(bbox[0], bbox[1], bbox[2], bbox[3], tmp)
        logger.debug(f"OCR区域截图已保存: {tmp}")

    # ── 拾取操作 ──────────────────────────────────────────

    def _pickup_one(self, cx: int, cy: int, monitor: TextMonitor) -> str:
        """执行一次拾取操作，返回 'picked' / 'unclickable' / 'storage_full'。"""
        hotkey = get_inventory_hotkey(self.hero_cfg, 0)
        key_time = self.war3_cfg["key_time"]

        # 先选中英雄，避免悬停识别物品时选中了其他单位
        self.dm.key_press_char("F1")
        time.sleep(key_time)
        self.dm.key_press_char(hotkey)
        time.sleep(key_time)
        self.dm.move_to(cx, cy)
        time.sleep(key_time)
        self.dm.left_click()

        unclickable_text = self.pickup_cfg.get("unclickable_text", "不可点击")
        storage_full_text = self.pickup_cfg.get("storage_full_text", "储物箱已满")
        timeout = self.pickup_cfg.get("result_timeout", 5)

        result = monitor.wait_for_any(
            [unclickable_text, storage_full_text], timeout=timeout
        )
        if result == unclickable_text:
            return "unclickable"
        elif result == storage_full_text:
            return "storage_full"
        else:
            return "picked"

    def _handle_unclickable(self, cx: int, cy: int, monitor: TextMonitor) -> bool:
        """不可点击 → ESC取消 → 等待 → 重试。返回 True 表示拾取成功。"""
        max_retries = self.pickup_cfg.get('max_retries', 3)
        retry_interval = self.pickup_cfg.get('retry_interval', 3)

        self.dm.key_press_char('esc')
        for attempt in range(1, max_retries + 1):
            time.sleep(retry_interval)
            logger.info(f"重试拾取({cx},{cy})，第 {attempt}/{max_retries} 次")
            result = self._pickup_one(cx, cy, monitor)
            if result == "storage_full":
                logger.error("储物箱已满，停止测试")
                self.storage_full = True
                return False
            if result == "picked":
                return True
            if result == "unclickable":
                self.dm.key_press_char('esc')
        logger.warning(f"宝箱({cx},{cy})重试 {max_retries} 次仍不可点击，跳过")
        return False

    # ── 辅助 ─────────────────────────────────────────────

    def _match_desired(self, item_name: str) -> Optional[str]:
        """判断 OCR 识别的物品名是否匹配目标物品且未达目标数量，返回匹配的物品名。

        匹配前先用配置中的 char_fixes 纠正 OCR 形近字误识别（如"廣"→"魔"）。
        """
        if not item_name:
            return None
        # OCR 形近字纠错
        char_fixes = self.item_text_cfg.get('char_fixes', {})
        if char_fixes:
            item_name = item_name.translate(str.maketrans(char_fixes))
        for name, info in self.item_targets.items():
            if name in item_name and info['picked'] < info['target']:
                return name
        return None

    def _all_items_satisfied(self) -> bool:
        """检查所有目标物品是否已拾取到目标数量。"""
        if not self.item_targets:
            return False
        return all(info['picked'] >= info['target'] for info in self.item_targets.values())

    @staticmethod
    def _parse_item_targets(desired_items: list) -> dict:
        """解析目标物品配置，支持 {name, count} 和纯字符串两种格式。"""
        targets = {}
        for item in desired_items:
            if isinstance(item, str):
                targets[item] = {'target': 1, 'picked': 0}
            elif isinstance(item, dict):
                name = item.get('name', '')
                count = item.get('count', 1)
                if name:
                    targets[name] = {'target': count, 'picked': 0}
        return targets

    def _log_progress(self):
        """输出各目标物品拾取进度。"""
        for name, info in self.item_targets.items():
            picked, target = info['picked'], info['target']
            if target > 0:
                logger.info(f"  进度: {name} {picked}/{target}")



def main():
    setup_global_exception_hook()
    logger.info("############################# 宝箱检测拾取测试 #############################")
    logger.info("5 秒后开始，请切换到 War3 游戏窗口...")
    time.sleep(5)
    cfg = config.load_task("war3.jiubing2.tasks.others.patrol_loot")
    test = ChestDetectTest(cfg)
    test.run()


if __name__ == "__main__":
    main()
