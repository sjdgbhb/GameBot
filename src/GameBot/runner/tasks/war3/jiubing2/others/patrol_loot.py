"""
巡逻拾取任务 — 在路线点循环杀怪，检测地面宝箱并拾取所需物品。
英雄已在游戏内即可运行，类似 endless_single.py。
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from GameBot.config import config
from GameBot.inference import get_inference_client
from GameBot.runner import create_dm_client
from GameBot.runner.business.war3 import TextMonitor, War3Business
from GameBot.runner.business.war3.jiubing2 import CombatHelper, GameUI, get_inventory_hotkey, get_inventory_hotkeys
from GameBot.runner.driver.wgc_capture import WgcCapture
from GameBot.runner.ui import run_with_float_window
from GameBot.utils import StopTaskError, logger, setup_log_file
from GameBot.utils.exception_handler import setup_global_exception_hook


class PatrolLootTask:
    """巡逻杀怪 + 宝箱拾取任务。"""

    def __init__(self, cfg: dict, stop_event=None, progress_lines_callback=None, dm=None):
        self.task_cfg = cfg
        self.cfg = cfg["war3"]["jiubing2"]["tasks"]["others"]["patrol_loot"]
        self.dm = dm or create_dm_client()
        self._stop_event = stop_event
        self._progress_lines_callback = progress_lines_callback

        war3_cfg = self.task_cfg.get("war3", {})
        hero_cfg = self.task_cfg.get("hero", {})

        self.war3 = War3Business(self.dm, war3_cfg)
        self.ui = GameUI(self.dm, war3_cfg, hero_cfg, self.task_cfg, self.war3)
        self.combat = CombatHelper(self.dm, war3_cfg, hero_cfg, self.task_cfg, self.war3)
        self.war3_cfg = war3_cfg
        self.hero_cfg = hero_cfg

        self.chest_cfg = self.task_cfg.get("chest", {})
        self.item_text_cfg = self.task_cfg.get("item_text", {})
        self.pickup_cfg = self.task_cfg.get("pickup", {})
        self.patrol_cfg = self.cfg.get("patrol", {})
        self.combat_cfg = self.task_cfg.get("combat_status", {})

        # 路线点解析：优先使用用户自定义 points，否则从 route_presets 按 route_scheme 选取
        self.route_scheme = self.cfg.get("route_scheme", "")
        self.route_presets = self.cfg.get("route_presets", [])
        self.points = self._resolve_points()

        self.hwnd = None
        self.pet_feed_time = time.time()
        self.item_targets = self._parse_item_targets(self.cfg.get("desired_items", []))
        self.storage_full = False

        # 初始上报进度
        self._report_progress()

        # 运行统计
        self._stats = {
            "start_time": 0.0,
            "rounds_completed": 0,
            "chests_detected": 0,
            "items_picked": {},  # {item_name: count}
            "items_skipped": 0,
            "non_target_names": [],  # 非目标物品名列表（供用户排查 OCR 误识别）
            "combat_wait_total": 0.0,
            "feed_count": 0,
        }

        # 可配置的等待/避让参数（从对应配置节点读取，缺省值与原硬编码一致）
        self.hover_wait_time = self.chest_cfg.get("hover_wait_time", 1.5)
        self.mouse_avoid_pos = self.cfg.get("mouse_avoid_pos", [200, 200])
        self.feed_only_interval = self.cfg.get("feed_only_interval", 10)
        self.combat_timeout = self.task_cfg.get("game", {}).get("combat_timeout", 120)

        # 预启动战斗检测线程（与移动等待并行）
        self._combat_check_thread = None
        self._combat_check_result = None
        self._combat_check_error = None

    # ── 主流程 ──────────────────────────────────────────

    def _resolve_points(self) -> list:
        """解析路线点：优先使用用户自定义 points，否则从 route_presets 按 route_scheme 选取。

        :return: 路线点列表
        """
        # 用户自定义 points 优先（通过 user_configs.json 覆盖）
        user_points = self.cfg.get("points")
        if user_points:
            return user_points
        # 按 route_scheme 从 route_presets 中选取
        if self.route_scheme and self.route_presets:
            for preset in self.route_presets:
                if preset.get("name") == self.route_scheme:
                    return preset.get("points", [])
            logger.warning(f"路线方案「{self.route_scheme}」未在 route_presets 中找到匹配项")
        # 兜底：空列表
        return []

    def run(self):
        rounds = self.patrol_cfg.get("rounds", 0)
        points = self.points
        logger.info(
            f"刷装备任务开始：路线方案「{self.route_scheme}」，路线点 {len(points)} 个，轮数 {'无限' if rounds == 0 else rounds}"
        )

        # 校验必须携带宠物食物（id=9），否则宠物会逃亡
        if not get_inventory_hotkeys(self.hero_cfg, 9):
            logger.error("未装备宠物食物（物品 id=9），任务拒绝启动")
            return

        hwnd = self.war3.find_game_window()
        if not hwnd:
            logger.error("未找到 war3 窗口")
            return

        # 尺寸调整放在绑定前：dx2 挂钩后 resize 会重建交换链导致闪屏
        self.war3.set_client_size(hwnd)
        with self.dm.bind_window(hwnd, bind_cfg=self.war3_cfg.get("bind", {})):
            self.run_core(hwnd)

    def run_core(self, hwnd, skip_feed_only=False):
        """核心巡逻循环 — 假设窗口已绑定。供 run() 和组队步骤调用。

        :param hwnd: War3 窗口句柄
        :param skip_feed_only: True 时跳过储物箱满后的仅喂宠物循环（组队模式用）
        """
        self.hwnd = hwnd
        self._stats["start_time"] = time.time()
        self.war3.set_client_size(hwnd)
        # 预初始化推理子进程（统一加载 OCR、宝箱检测、战斗检测模型）
        logger.info("正在初始化推理子进程（OCR + AI 模型）...")
        get_inference_client()
        logger.info("模型初始化完成")
        rounds = self.patrol_cfg.get("rounds", 0)
        points = self.points
        monitor = None
        try:
            monitor = self._make_monitor(hwnd)
            round_idx = 0
            while rounds == 0 or round_idx < rounds:
                if self.storage_full:
                    logger.info("储物箱已满，停止巡逻")
                    break
                if self._all_items_satisfied():
                    logger.info("所有目标物品已拾取完毕，停止巡逻")
                    break
                round_idx += 1
                logger.info(f"===== 巡逻第 {round_idx} 轮开始 =====")
                try:
                    for i, pt in enumerate(points):
                        self._navigate_to_point(pt)
                        self._kill_monsters(pt)
                        self._feed_pet()
                        self._pickup_loop(monitor)
                        if self.storage_full or self._all_items_satisfied():
                            break
                except StopTaskError:
                    if monitor is not None and monitor.error is not None:
                        raise monitor.error
                    logger.info("用户请求停止，终止巡逻")
                    break
                self._stats["rounds_completed"] = round_idx
                logger.info(f"===== 巡逻第 {round_idx} 轮结束 =====")
            # 储物箱满或物品拾取完毕后，继续定时喂宠物
            if not skip_feed_only and (self.storage_full or self._all_items_satisfied()):
                self._feed_only_loop()
        finally:
            if monitor is not None:
                monitor.stop()
            self._log_stats()

        logger.info("刷装备任务结束")

    def _make_monitor(self, hwnd: int):
        atomic_task_cfg = self.task_cfg.get("atomic_task", {})
        interval = atomic_task_cfg.get("monitor_interval", 0.2)
        # 监测线程截图出错 → set stop_event 让主线程尽快中断，异常由 monitor.stop() 抛出
        monitor = TextMonitor(
            self.war3, self.task_cfg.get("prompt_text"), interval=interval, on_error=self._on_monitor_error
        )
        monitor.start(hwnd)
        return monitor

    def _on_monitor_error(self, _exc: BaseException):
        if self._stop_event is not None:
            self._stop_event.set()

    # ── 路线点导航 & 杀怪 ────────────────────────────────

    def _interruptible_wait(self, seconds: float):
        """可被停止信号中断的等待，检测到停止时抛出 StopTaskError。"""
        if self._stop_event is not None:
            if self._stop_event.wait(seconds):
                raise StopTaskError("用户请求停止任务")
        else:
            time.sleep(seconds)

    def _navigate_to_point(self, pt: dict):
        self.dm.key_press_char("F1")
        self._interruptible_wait(self.war3_cfg["key_time"])
        wait_time = pt.get("time", 3)
        logger.info(f"目标位置：{pt['desc']}，等待时间：{wait_time}s")
        # 启动持续战斗检测线程，与移动等待并行，移动期间持续循环检测
        self._start_combat_check()
        self.war3.move_to_minimap_point(
            pt.get("mini_coords"),
            pt.get("coords"),
            pt.get("walk_mode", 1),
            wait_time,
            stop_event=self._stop_event,
        )

    def _kill_monsters(self, pt: dict):
        self.combat.execute_actions(pt, pt.get("coords"), stop_event=self._stop_event)

    # ── 战斗状态检测 ──────────────────────────────────────

    def _start_combat_check(self):
        """启动持续战斗检测线程，在移动等待期间循环检测战斗状态。

        线程每轮用 WGC 抓 frame_count 帧头像区域（frame_interval 间隔），
        送入 ONNX 战斗分类模型，将最新结果存入 _combat_check_result，
        直到 _stop_combat_check 被调用。如果线程已在运行则不重复启动。
        """
        if self._combat_check_thread is not None and self._combat_check_running:
            return
        cfg = self.combat_cfg
        area = cfg["in_combat_area_coords"]
        frame_count = cfg.get("frame_count", 10)
        frame_interval = cfg.get("frame_interval", 0.3)
        wgc_min_interval = self.war3_cfg.get("wgc_min_interval_ms", 100)

        self._combat_check_result = None
        self._combat_check_error = None
        self._combat_check_round = 0
        self._combat_check_running = True

        def _do_check():
            cap = WgcCapture.for_hwnd(self.hwnd, min_interval_ms=wgc_min_interval)
            while self._combat_check_running:
                try:
                    frames = []
                    for i in range(frame_count):
                        if not self._combat_check_running:
                            break
                        frames.append(cap.grab_client(area))
                        if i < frame_count - 1:
                            time.sleep(frame_interval)
                    self._combat_check_result = get_inference_client().predict_combat_from_arrays(frames)
                    self._combat_check_round += 1
                except Exception as e:
                    self._combat_check_error = e
                    self._combat_check_running = False
                    return

        self._combat_check_thread = threading.Thread(target=_do_check, daemon=True)
        self._combat_check_thread.start()

    def _stop_combat_check(self):
        """停止持续战斗检测线程，等待线程退出。"""
        self._combat_check_running = False
        if self._combat_check_thread is not None:
            self._combat_check_thread.join(timeout=5)
            self._combat_check_thread = None

    def _wait_non_combat(self):
        """等待英雄脱离战斗状态，超时后强制继续。

        内部管理战斗检测线程的启停：线程已停止则重新启动，脱战后直接 join 停止线程。
        调用方无需关心线程管理。
        """
        # 线程已停止则重新启动
        if self._combat_check_thread is None or not self._combat_check_running:
            self._start_combat_check()

        start = time.time()
        # 记录当前轮次，后续只看比这更新的轮次
        baseline_round = self._combat_check_round
        logger.debug(f"等待脱战检测（当前轮次 {baseline_round}）...")

        while True:
            # 等待新一轮检测完成（比 baseline_round 更新）
            while self._combat_check_round <= baseline_round:
                if self._combat_check_error is not None:
                    logger.warning(f"战斗状态检测失败：{self._combat_check_error}，保守判定为战斗中")
                    self._stop_combat_check()
                    return
                if time.time() - start >= self.combat_timeout:
                    logger.warning(f"等待战斗检测超时（{self.combat_timeout}s），强制继续")
                    self._stats["combat_wait_total"] += time.time() - start
                    self._stop_combat_check()
                    return
                if self._stop_event is not None:
                    if self._stop_event.wait(0.2):
                        raise StopTaskError("用户请求停止任务")
                else:
                    time.sleep(0.2)

            # 有新一轮结果了
            if self._combat_check_error is not None:
                logger.warning(f"战斗状态检测失败：{self._combat_check_error}，保守判定为战斗中")
                self._stop_combat_check()
                return

            results = self._combat_check_result or [False]
            in_combat = any(results)
            if not in_combat:
                wait_time = time.time() - start
                if wait_time > 0.5:
                    logger.info(f"英雄已脱离战斗（等待 {wait_time:.1f}s）")
                self._stats["combat_wait_total"] += wait_time
                # 脱战后直接停止线程并 join，调用方无需再显式调用 _stop_combat_check
                self._stop_combat_check()
                return

            # 仍在战斗，等待下一轮检测
            logger.debug(f"AI检测: {sum(results)}/{len(results)} 帧判定战斗，继续等待...")
            baseline_round = self._combat_check_round

    # ── 拾取循环 ──────────────────────────────────────────

    def _pickup_loop(self, monitor: TextMonitor):
        """脱战后循环检测宝箱 → 边识别边拾取 → 再次检测宝箱。

        循环终止条件：本轮未检测到宝箱、或本轮未检测到目标物品、或达到最大检测次数 3 次。
        每次检测宝箱前均确保英雄处于脱战状态。
        """
        if self._all_items_satisfied():
            logger.info("所有目标物品已拾取完毕，跳过拾取")
            return

        max_rounds = 3
        for round_idx in range(1, max_rounds + 1):
            # 确保脱战状态后再检测宝箱（_wait_non_combat 内部会停止线程）
            self._wait_non_combat()

            chests = self._find_all_chests()
            if not chests:
                logger.info(f"第 {round_idx} 轮检测：未检测到地面宝箱，拾取结束")
                break
            logger.info(f"第 {round_idx} 轮检测：发现 {len(chests)} 个宝箱")
            self._stats["chests_detected"] += len(chests)
            found_target_this_round = False
            for idx, cx, cy, conf in chests:
                if self.storage_full or self._all_items_satisfied():
                    break
                picked = self._try_pickup_chest(idx, cx, cy, conf, monitor)
                if picked is not None:
                    found_target_this_round = True
                    # 拾取后重置游戏状态：ESC 取消技能瞄准，鼠标移开清 tooltip，等待英雄稳定
                    self.dm.key_press_char("esc")
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
            self.war3.send_msg(self.task_cfg["command"]["clear_nearby"])
            logger.info("已清理地面物品")

    def _try_pickup_chest(self, idx, cx, cy, conf, monitor: TextMonitor) -> Optional[bool]:
        """识别单个宝箱物品并尝试拾取。

        :return: True=拾取成功(含重试), False=检测到目标但拾取失败, None=非目标/未识别
        """
        self.dm.move_to(cx, cy)
        time.sleep(self.hover_wait_time)
        item_name = self._read_item_name(cx, cy)
        matched_item = self._match_desired(item_name)

        if not (item_name and matched_item):
            self._stats["items_skipped"] += 1
            if item_name and item_name not in self._stats["non_target_names"]:
                self._stats["non_target_names"].append(item_name)
            logger.info(f"宝箱#{idx} ({cx},{cy}) conf={conf:.2f} → [非目标] {item_name or '(未识别)'} → 跳过")
            return None

        result = self._pickup_one(cx, cy, monitor)
        if result == "storage_full":
            logger.error("储物箱已满，停止刷装备")
            self.storage_full = True
            return False
        elif result == "unclickable":
            logger.info(f"宝箱#{idx} ({cx},{cy}) conf={conf:.2f} → [目标] {item_name} → 拾取失败：不可点击")
            success = self._handle_unclickable(cx, cy, monitor)
            if success:
                self._mark_picked(matched_item, item_name)
                logger.info(
                    f"宝箱#{idx} ({cx},{cy}) → 重试拾取成功（{self.item_targets[matched_item]['picked']}/{self.item_targets[matched_item]['target']}）"
                )
            else:
                logger.info(f"宝箱#{idx} ({cx},{cy}) → 重试失败，跳过")
            return success
        else:
            self._mark_picked(matched_item, item_name)
            logger.info(
                f"宝箱#{idx} ({cx},{cy}) conf={conf:.2f} → [目标] {item_name} → 拾取成功（{self.item_targets[matched_item]['picked']}/{self.item_targets[matched_item]['target']}）"
            )
            return True

    def _mark_picked(self, matched_item: str, item_name: str):
        """记录拾取成功：更新目标计数、统计、上报进度。"""
        self.item_targets[matched_item]["picked"] += 1
        self._stats["items_picked"][matched_item] = self._stats["items_picked"].get(matched_item, 0) + 1
        self._report_progress()

    def _feed_pet(self):
        """喂宠物（间隔由 jiubing2.toml [pet].feeding_interval 控制）。"""
        old_feed_time = getattr(self, "pet_feed_time", time.time())
        self.combat.feed_pet(self)
        # 统计喂食次数（feed_pet 内部更新 pet_feed_time，通过时间变化判断是否实际喂食）
        if hasattr(self, "pet_feed_time") and self.pet_feed_time != old_feed_time:
            self._stats["feed_count"] += 1

    def _handle_unclickable(self, cx: int, cy: int, monitor: TextMonitor) -> bool:
        """不可点击 → ESC取消 → 等待 → 重试。返回 True 表示拾取成功。"""
        max_retries = self.pickup_cfg.get("max_retries", 3)
        retry_interval = self.pickup_cfg.get("retry_interval", 3)

        self.dm.key_press_char("esc")
        for attempt in range(1, max_retries + 1):
            self._interruptible_wait(retry_interval)
            logger.info(f"重试拾取({cx},{cy})，第 {attempt}/{max_retries} 次")
            result = self._pickup_one(cx, cy, monitor)
            if result == "storage_full":
                logger.error("储物箱已满，停止刷装备")
                self.storage_full = True
                return False
            if result == "picked":
                return True
            if result == "unclickable":
                self.dm.key_press_char("esc")
        logger.warning(f"宝箱({cx},{cy})重试 {max_retries} 次仍不可点击，跳过")
        return False

    def _pickup_one(self, cx: int, cy: int, monitor: TextMonitor) -> str:
        """执行一次拾取操作，返回 'picked' / 'unclickable' / 'storage_full'。"""
        hotkey = get_inventory_hotkey(self.hero_cfg, 0)
        key_time = self.war3_cfg["key_time"]

        # 先选中英雄，避免悬停识别物品时选中了其他单位
        self.dm.key_press_char("F1")
        self._interruptible_wait(key_time)
        self.dm.key_press_char(hotkey)
        self._interruptible_wait(key_time)
        self.dm.move_to(cx, cy)
        self._interruptible_wait(key_time)
        self.dm.left_click()

        unclickable_text = self.pickup_cfg.get("unclickable_text", "不可点击")
        storage_full_text = self.pickup_cfg.get("storage_full_text", "储物箱已满")
        timeout = self.pickup_cfg.get("result_timeout", 5)

        result = monitor.wait_for_any([unclickable_text, storage_full_text], timeout=timeout)
        if result == unclickable_text:
            return "unclickable"
        elif result == storage_full_text:
            return "storage_full"
        else:
            return "picked"  # 超时无错误提示 = 拾取成功

    # ── 宝箱检测 ──────────────────────────────────────────

    def _find_all_chests(self):
        """全客户区 AI 检测宝箱（WGC 取帧），返回 [(index, x, y, confidence), ...]，x/y 为宝箱中心坐标。"""
        # 截图前用大漠 MoveTo 移动鼠标到远处，触发 war3 tooltip 消失
        avoid_x, avoid_y = self.mouse_avoid_pos
        self.dm.move_to(avoid_x, avoid_y)
        time.sleep(0.15)

        # WGC 整客户区帧（客户区坐标），检测返回的坐标即客户区坐标
        wgc_min_interval = self.war3_cfg.get("wgc_min_interval_ms", 100)
        cap = WgcCapture.for_hwnd(self.hwnd, min_interval_ms=wgc_min_interval)
        cw, ch = cap.client_size()
        img = cap.grab_client((0, 0, cw, ch))
        t0 = time.time()
        detections = get_inference_client().detect_chests_from_array(img)
        logger.debug(f"宝箱检测耗时: {time.time() - t0:.3f}s，检测到 {len(detections) if detections else 0} 个")
        if not detections:
            return []

        results = []
        for i, (x1, y1, x2, y2, confidence) in enumerate(detections):
            cx_pt = (x1 + x2) // 2
            cy_pt = (y1 + y2) // 2
            results.append((i, cx_pt, cy_pt, confidence))
        return results

    # ── 物品名称 OCR ──────────────────────────────────────

    def _read_item_name(self, chest_x: int, chest_y: int) -> str:
        """OCR 读取宝箱上方区域的物品名称。"""
        offset_y = self.item_text_cfg.get("offset_y", 50)
        half_w = self.item_text_cfg.get("area_width", 200) // 2
        half_h = self.item_text_cfg.get("area_height", 60) // 2

        text_y = chest_y - offset_y
        area_coords = [
            chest_x - half_w,
            text_y - half_h,
            chest_x + half_w,
            text_y + half_h,
        ]
        text = self.war3.ocr_text(self.hwnd, {"area_coords": area_coords})
        return self.war3._normalize_ocr(text)

    # ── 辅助 ──────────────────────────────────────────────

    def _match_desired(self, item_name: str) -> Optional[str]:
        """判断 OCR 识别的物品名是否匹配目标物品且未达目标数量，返回匹配的物品名。

        匹配前先用配置中的 char_fixes 纠正 OCR 形近字误识别（如"廣"→"魔"）。
        """
        if not item_name:
            return None
        # OCR 形近字纠错
        char_fixes = self.item_text_cfg.get("char_fixes", {})
        if char_fixes:
            item_name = item_name.translate(str.maketrans(char_fixes))
        for name, info in self.item_targets.items():
            if name in item_name and info["picked"] < info["target"]:
                return name
        return None

    @staticmethod
    def _parse_item_targets(desired_items: list) -> dict:
        """解析目标物品配置，支持新旧两种格式。

        新格式：[{name = "xxx", count = N}, ...]
        旧格式：["xxx", ...]（默认 count = 1）
        """
        targets = {}
        for item in desired_items:
            if isinstance(item, str):
                targets[item] = {"target": 1, "picked": 0}
            elif isinstance(item, dict):
                name = item.get("name", "")
                count = item.get("count", 1)
                if name:
                    targets[name] = {"target": count, "picked": 0}
        return targets

    def _all_items_satisfied(self) -> bool:
        """检查所有目标物品是否已拾取到目标数量。"""
        if not self.item_targets:
            return False
        return all(info["picked"] >= info["target"] for info in self.item_targets.values())

    def _report_progress(self):
        """上报各装备拾取进度到浮窗，每行一件装备。"""
        if self._progress_lines_callback is None:
            return
        lines = []
        for name, info in self.item_targets.items():
            picked, target = info["picked"], info["target"]
            if target <= 0:
                continue
            lines.append(f"{name} {picked}/{target}")
        self._progress_lines_callback(lines)

    def _log_stats(self):
        """输出运行统计摘要。"""
        s = self._stats
        elapsed = time.time() - s["start_time"] if s["start_time"] else 0
        picked_summary = ", ".join(f"{name}×{count}" for name, count in s["items_picked"].items()) or "无"
        non_target_summary = ", ".join(s["non_target_names"]) if s["non_target_names"] else "无"
        logger.info(
            f"===== 巡逻统计 ===== "
            f"耗时 {elapsed:.0f}s | "
            f"完成 {s['rounds_completed']} 轮 | "
            f"检测宝箱 {s['chests_detected']} 个 | "
            f"拾取: {picked_summary} | "
            f"跳过 {s['items_skipped']} 个 | "
            f"战斗等待 {s['combat_wait_total']:.0f}s | "
            f"喂食 {s['feed_count']} 次"
        )
        logger.info(f"非目标物品名列表: {non_target_summary}")

    def _feed_only_loop(self):
        """储物箱满或物品拾取完毕后，仅定时喂宠物。"""
        logger.info("进入仅喂宠物模式，按 Num- 停止")
        while True:
            self._feed_pet()
            self._interruptible_wait(self.feed_only_interval)


def main():
    setup_global_exception_hook()
    setup_log_file("刷装备")
    logger.info("############################# 刷装备任务 #############################")

    cfg = config.load_task("war3.jiubing2.tasks.others.patrol_loot")
    route_scheme = cfg["war3"]["jiubing2"]["tasks"]["others"]["patrol_loot"].get("route_scheme", "")
    title = f"刷装备（{route_scheme}）" if route_scheme else "刷装备"

    def task_wrapper(stop_event, progress_callback=None, **kwargs):
        task = PatrolLootTask(cfg, stop_event=stop_event, progress_lines_callback=kwargs.get("progress_lines_callback"))
        task.run()

    run_with_float_window(title, task_wrapper, countdown_seconds=5, float_cfg=cfg.get("float_window", {}))


if __name__ == "__main__":
    main()


# ── 组队任务步骤 ────────────────────────────────────────────


from GameBot.runner.business.war3.jiubing2.team_steps_base import Jiubing2TaskSteps


class _PatrolLootSteps(Jiubing2TaskSteps):
    """刷装备组队步骤 — position_init 导航至巡逻区域，run_task 执行巡逻拾取。"""

    def position_init(self, member, stop_event=None, **kwargs):
        """就位 — 折叠属性面板 → TP至米奈希尔 → 点击复活石传送至巡逻区域 → 移动到路线最后一个点。

        使用米奈希尔tp -> 点击米奈希尔复活石里的传送至 strange_land/unknown_cave 无延迟 -> 对应路线的最后一个位置。
        """
        from GameBot.runner.business.war3.jiubing2.team_steps_base import _build_business_objects

        ui, nav, combat, runner = _build_business_objects(member)
        patrol_cfg = (
            member.task_cfg.get("war3", {})
            .get("jiubing2", {})
            .get("tasks", {})
            .get("others", {})
            .get("patrol_loot", {})
        )

        if not patrol_cfg:
            logger.error("position_init 缺少 patrol_loot 配置")
            member._flow_failed = True
            return

        route_scheme = patrol_cfg.get("route_scheme", "")
        points = patrol_cfg.get("points", [])
        if not points:
            route_presets = patrol_cfg.get("route_presets", [])
            for preset in route_presets:
                if preset.get("name") == route_scheme:
                    points = preset.get("points", [])
                    break

        if not points:
            logger.error(f"路线方案「{route_scheme}」未找到路线点")
            member._flow_failed = True
            return

        logger.info(f"组队刷装备就位：路线方案「{route_scheme}」，路线点 {len(points)} 个")
        ui.switch_attribute_panel(is_fold=True)
        # TP至米奈希尔 → 点击复活石传送至巡逻区域
        nav.tp_to_patrol_area(route_scheme, stop_event)
        # 移动到路线最后一个点（靠近裂隙，方便后续巡逻循环从第一个点开始）
        last_pt = points[-1]
        member.war3.move_to_minimap_point(
            last_pt.get("mini_coords"),
            last_pt.get("coords"),
            last_pt.get("walk_mode", 1),
            last_pt.get("time", 3),
            stop_event=stop_event,
        )
        logger.info("组队刷装备就位完成")

    def run_task(self, member, stop_event=None, **kwargs):
        """巡逻杀怪 + 宝箱拾取主循环。"""
        # 校验必须携带宠物食物（id=9），否则宠物会逃亡
        if not get_inventory_hotkeys(member.hero_cfg, 9):
            logger.error("未装备宠物食物（物品 id=9），任务拒绝启动")
            member._flow_failed = True
            return

        task = PatrolLootTask(member.task_cfg, stop_event=stop_event, dm=member.dm)
        hwnd = member._current_war3_hwnd
        if not hwnd:
            logger.error("run_task 无可用 War3 窗口句柄")
            member._flow_failed = True
            return
        try:
            task.run_core(hwnd, skip_feed_only=True)
        except StopTaskError:
            logger.info("用户请求停止刷装备")
            raise
        except Exception as e:
            logger.error(f"刷装备任务异常: {e}")
            member._flow_failed = True

    def pre_exit(self, member, stop_event: Optional[threading.Event] = None, **kwargs) -> None:
        """退出前无需额外操作（存档由路线点 action 触发）。"""
        pass


_steps = _PatrolLootSteps()
preparation = _steps.preparation
position_init = _steps.position_init
pre_exit = _steps.pre_exit
run_task = _steps.run_task
