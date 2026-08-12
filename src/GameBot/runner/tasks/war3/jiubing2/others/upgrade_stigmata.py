"""
升级圣痕任务 — 每完成一次黑石城城门骚扰任务获得一次圣痕升级机会，机会不可叠加，
故采用"城门骚扰(获取机会) → 走到圣痕NPC → 升级一次 → 返回守卫队长"交替循环，直至所有待升级词条达标。

复用 AtomicLoopTask 的公共对象装配与单次原子任务执行逻辑（_run_one_atomic）。
配置通过 config.load_task("war3.jiubing2.tasks.others.upgrade_stigmata") 加载，
其依赖 tasks.atomic.blackstone_gate_harassment（复用 prompt_text 检测区域与城门骚扰配置）。
"""
import copy
import re
import time

from GameBot.utils import logger, StopTaskError, setup_log_file
from GameBot.config import config
from GameBot.utils.exception_handler import setup_global_exception_hook, DmError
from GameBot.inference import get_ocr_client
from GameBot.runner.ui import run_with_float_window
from GameBot.runner.tasks.war3.jiubing2.base import AtomicLoopTask
from GameBot.runner.tasks.war3.jiubing2.atomic.blackstone_gate_harassment import GateHarassmentTask

# 原子任务运行期可重试异常（与 base.py 保持一致）
_ATOMIC_RETRYABLE_EXC = (DmError, RuntimeError, TimeoutError, OSError)

# 词条缩写和位置标签从 stigmata 配置读取（term_short / pos_labels）


class UpgradeStigmataTask(AtomicLoopTask):
    """升级圣痕 — 交替执行城门骚扰(获取机会)与圣痕升级，直到所有词条达标。"""

    atomic_task_cls = GateHarassmentTask
    atomic_name = "城门骚扰"
    task_config_path = ("war3", "jiubing2", "tasks", "others", "upgrade_stigmata")
    atomic_config_path = ("war3", "jiubing2", "tasks", "atomic", "blackstone_gate_harassment")

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.upgrade_cfg = self.cfg  # 别名，与既有代码保持一致

    @property
    def task_name(self) -> str:
        return self.upgrade_cfg.get("name", "升级圣痕")

    @property
    def _npc(self) -> dict:
        """圣痕升级 NPC 配置（来自依赖闭包的 blackstone_city 场景）。"""
        return (self.full_cfg.get("scenes", {}).get("blackstone_city", {})
                .get("npcs", {}).get("stigmata", {}))

    @property
    def _board(self) -> dict:
        """圣痕技能板布局配置（flip_grid + 各位置 [页, 行]）。"""
        return self._npc.get("board", {})

    @property
    def _layout(self) -> dict:
        return self._board.get("layout", {})

    @property
    def _flip_grid(self) -> list:
        return self._board.get("flip_grid", [3, 4])

    @property
    def _ocr_cfg(self) -> dict:
        # 复用游戏底层的提示检测区域（升级成功/失败提示同区域、出现很快）
        return self.full_cfg.get("prompt_text")

    def _interruptible_wait(self, seconds: float):
        """可被停止信号中断的等待，检测到停止时抛出 StopTaskError。"""
        if self._stop_event is not None:
            if self._stop_event.wait(seconds):
                raise StopTaskError("用户请求停止任务")
        else:
            time.sleep(seconds)

    def _walk_to_point(self, pt: dict):
        """按路线点配置行走（F1 重置视角 → 小地图点击移动）。"""
        desc = pt.get("desc", "未知路线点")
        wait_time = pt.get("time", 5)
        logger.info(f"走到：{desc}，预计 {wait_time} 秒）")
        gt = self.war3_cfg['general_time']
        self.dm.key_press_char('F1')
        self._interruptible_wait(gt)
        self.war3.move_to_minimap_point(
            pt["mini_coords"], pt["coords"],
            mode=pt.get("walk_mode", 1),
            wait_time=wait_time,
            stop_event=self._stop_event,
        )

    def _build_atomic_cfg(self) -> dict:
        """构建城门骚扰原子任务的有效配置（使用原子任务自身的路线点）。"""
        return copy.deepcopy(self.atomic_cfg)

    def _run_one_atomic(self, at_npc: bool = False,
                        walk_time=None, monitor=None) -> bool:
        """执行一次城门骚扰原子任务，返回是否成功。"""
        task = self.atomic_task_cls(
            self.dm, self.war3, self.ui, self.combat,
            self._build_atomic_cfg(),
            at_npc=at_npc, walk_time=walk_time, monitor=monitor,
            nearby_cleaner=self.nearby_cleaner,
        )
        try:
            return task.run(stop_event=self._stop_event)
        except StopTaskError:
            raise
        except _ATOMIC_RETRYABLE_EXC as e:
            logger.error(f"{self.atomic_name}任务异常：{e}")
            return False

    # ── 主流程 ──────────────────────────────────────────

    def run(self, stop_event=None, progress_lines_callback=None):
        self._stop_event = stop_event
        self._progress_lines = progress_lines_callback
        success_text = self.upgrade_cfg.get("success_text", "成功")
        fail_text = self.upgrade_cfg.get("fail_text", "失败")
        loop_interval = self.upgrade_cfg.get("loop_interval_time", 1.0)
        points = self.cfg.get("points", [])
        walk_to_stigmata = points[0] if len(points) > 0 else {}
        walk_to_guard = points[1] if len(points) > 1 else {}

        stigmata_cfg = self.full_cfg.get("stigmata", {})
        term_limit = stigmata_cfg.get("term_limit", {})
        if not term_limit:
            logger.error("未配置 stigmata.term_limit，无法判断升级目标")
            return

        logger.info(f"{self.task_name}开始：词条上限配置 {term_limit}")

        # 若配置了技能 action 但未选择英雄，后续 resolve_point_skills 会自然失败，这里仅记录
        if any(any(a.get('type') == 'skill' for a in (pt.get("actions") or []))
               for pt in self.cfg.get("points", [])) and not self.hero_cfg.get("skills"):
            logger.error("路线点配置了技能但未选择有技能的英雄")
            return

        hwnd = self.dm.get_active_window(
            self.war3_cfg["window_class"], self.war3_cfg["window_title"]
        )
        if not hwnd:
            logger.error("未找到 war3 窗口")
            return

        with self.dm.bind_window(hwnd):
            self.war3.set_client_size(hwnd)
            get_ocr_client(load_chest=False, load_combat=False)  # 预热 OCR 子进程（仅需 OCR，不加载 AI 模型）
            # 启动持续文字监测线程（整段脚本运行期间常驻，城门骚扰完成与升级结果共用）
            monitor = self._make_monitor(hwnd)
            try:
                attempts = 0
                at_guard_captain = False  # 英雄是否在守卫队长旁（首轮不在，后续轮在）
                while True:
                    # 1) 读取圣痕面板，找到未达上限的词条
                    stats = self.read_stigmata_stats(hwnd)
                    if not stats:
                        logger.warning("读取圣痕面板失败，重试")
                        self._interruptible_sleep(loop_interval)
                        continue

                    target = self._pick_upgrade_target(stats, term_limit)
                    self._update_float_lines(stats, term_limit, target)
                    if target is None:
                        logger.info("所有词条已达上限，任务完成")
                        break

                    pos, idx, term_name, current_val, limit_val = target
                    attempts += 1
                    logger.info(
                        f"===== 第 {attempts} 次升级循环：{pos} {term_name} "
                        f"当前 {current_val}/{limit_val} ====="
                    )

                    # 2) 完成一次城门骚扰以获得升级机会（机会不可叠加，故每次必先做任务）
                    #    首轮英雄不在守卫队长旁，需行走；
                    #    后续轮英雄已在守卫队长旁（上轮升级后走回），at_npc=True 跳过行走。
                    if not self._run_one_atomic(
                        at_npc=at_guard_captain,
                        walk_time=None,
                        monitor=monitor
                    ):
                        logger.warning("城门骚扰未完成，未获得升级机会，重试")
                        self._interruptible_sleep(loop_interval)
                        continue

                    # 3) 走到圣痕NPC
                    self._walk_to_point(walk_to_stigmata)

                    # 4) 选中圣痕NPC并升级选中的词条
                    matched = self._upgrade_once(pos, idx, success_text, fail_text, monitor)
                    if matched == success_text:
                        logger.info(f"升级成功：{pos} {term_name}")
                    elif matched == fail_text:
                        logger.warning(f"升级失败：{pos} {term_name}（机会已消耗）")
                    else:
                        logger.info(f"未检测到成功/失败提示：{pos} {term_name}")

                    # 5) 返回守卫队长旁，为下一轮城门骚扰做准备
                    self._walk_to_point(walk_to_guard)
                    at_guard_captain = True

                    self._interruptible_sleep(loop_interval)
            except StopTaskError:
                logger.info("用户请求停止，终止圣痕升级")
            finally:
                if monitor is not None:
                    monitor.stop()

        logger.info(f"{self.task_name}结束：共尝试 {attempts} 次")

    # ── 圣痕升级 ──────────────────────────────────────────

    def _upgrade_once(self, pos: str, idx: int,
                      success_text: str, fail_text: str, monitor=None) -> bool:
        """选中圣痕NPC → (下位需翻页) → 点击对应技能格 → 检测成功/失败。

        行走步骤由调用方通过 _walk_to_point(walk_to_stigmata) 完成，本方法仅处理 NPC 交互。
        """
        gt = self.combat.war3_cfg['general_time']
        swt = self.combat.war3_cfg['small_window_response_time']
        npc = self._npc
        coords = npc['coords']

        # 点击圣痕NPC选中（选中后技能板翻页重置为第1页）
        self.dm.move_to(*coords)
        self._interruptible_wait(gt)
        self.dm.left_click()
        self._interruptible_wait(swt)

        # 下位在第2页，需先点翻页按钮
        page, row = self._layout.get(pos, [1, 1])
        if page == 2:
            fx, fy = self.ui.get_skill_coords(*self._flip_grid)
            self.dm.move_to(fx, fy)
            self._interruptible_wait(gt)
            self.dm.left_click()
            self._interruptible_wait(swt)

        # 点击对应词条的技能格（列 = idx + 1）
        col = idx + 1
        sx, sy = self.ui.get_skill_coords(row, col)
        self.dm.move_to(sx, sy)
        self._interruptible_wait(gt)
        self.dm.left_click()

        # 检测成功/失败提示（与接任务文本提示同区域、同方式）；
        # 优先用持续 monitor（实时性更好），无则回退到 war3 阻塞轮询。
        # 返回命中文字（success_text / fail_text）；超时均未命中则返回 None，
        # 调用方据此判定该词条已升满（满词条点击后不弹成功/失败提示）。
        result_timeout = self.upgrade_cfg.get("result_timeout", 8)
        if monitor is not None:
            matched = monitor.wait_for_any(
                [success_text, fail_text], timeout=result_timeout,
            )
        else:
            matched = self.war3.wait_for_any_text(
                self._ocr_cfg, [success_text, fail_text],
                timeout=result_timeout,
                interval=self.upgrade_cfg.get("result_check_interval", 0.5),
            )
        return matched

    def _update_float_lines(self, stats: dict, term_limit: dict, target=None):
        """格式化圣痕词条数值为多行文本，推送到浮窗显示。"""
        if self._progress_lines is None:
            return
        term_short = self.upgrade_cfg.get("term_short", {})
        pos_labels = self.upgrade_cfg.get("pos_labels", {})
        lines = []
        for pos in ("upper", "core", "middle", "lower"):
            terms = stats.get(pos, [])
            if not terms:
                continue
            label = pos_labels.get(pos, pos)
            parts = []
            for name, val in terms:
                short = term_short.get(name, name)
                limit = term_limit.get(name, "?")
                parts.append(f"{short}{int(val)}/{limit}")
            lines.append(f"{label}: {' '.join(parts)}")
        self._progress_lines(lines)

    # ── 圣痕面板 OCR 读取 ──────────────────────────────────

    @staticmethod
    def _parse_stigmata_text(full_text: str, term_limit: dict) -> dict:
        """解析圣痕面板 OCR 全文，提取各位置词条数值。

        :param full_text: OCR 识别的完整文本（多行合并）
        :param term_limit: 词条上限配置 {term_name: limit, ...}
        :return: {"upper": [(term_name, value), ...], "core": [...], ...}
        """
        pos_keywords = {"上位": "upper", "核心": "core", "中位": "middle", "下位": "lower"}
        result = {}

        segments = re.split(r'(上位|核心|中位|下位)', full_text)
        current_pos = None
        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue
            if seg in pos_keywords:
                current_pos = pos_keywords[seg]
                result[current_pos] = []
                continue
            if current_pos is None:
                continue
            # 在段中按出现顺序查找各词条名及其数值
            found = []
            for term_name in term_limit:
                pos_in_seg = seg.find(term_name)
                if pos_in_seg >= 0:
                    after = seg[pos_in_seg + len(term_name):]
                    m = re.search(r'(\d+\.?\d*)', after)
                    if m:
                        found.append((pos_in_seg, term_name, float(m.group(1))))
            found.sort(key=lambda x: x[0])
            for _, name, val in found:
                result[current_pos].append((name, val))

        return result

    def read_stigmata_stats(self, hwnd) -> dict:
        """按 F2 打开圣痕面板，OCR 读取各位置词条当前数值。

        :param hwnd: war3 窗口句柄
        :return: {"upper": [(term_name, value), ...], "core": [...], ...}
                 term_name 对应 term_limit 的 key，value 为当前数值；
                 列表顺序与技能格列号一致（idx 0=第1列）。
        """
        stigmata_cfg = self.full_cfg.get("stigmata", {})
        num_coords = stigmata_cfg.get("num_coords")
        hotkey = stigmata_cfg.get("switch_hotkey", "F2")
        if not num_coords:
            logger.warning("未配置 stigmata.num_coords，无法 OCR 圣痕面板")
            return {}

        # 客户区坐标转屏幕坐标（OCR 子进程用 ImageGrab.grab 是屏幕坐标）
        cx, cy, _, _ = self.dm.get_client_rect(hwnd)
        screen_bbox = [cx + num_coords[0], cy + num_coords[1],
                       cx + num_coords[2], cy + num_coords[3]]

        # 按 F2 打开圣痕面板
        self.dm.key_press_char(hotkey)
        self._interruptible_wait(self.war3_cfg.get('small_window_response_time', 0.5))

        # OCR 读取圣痕词条区域
        client = get_ocr_client()
        lines = client.ocr_lines(screen_bbox)
        logger.debug(f"圣痕面板 OCR 原始行(首次): {lines}")

        # 行数不足 4 时，对下半部分单独二次 OCR（RapidOCR 可能漏检底部行）
        if len(lines) < 4:
            x1, y1, x2, y2 = screen_bbox
            mid_y = y1 + (y2 - y1) // 2
            lower_bbox = [x1, mid_y, x2, y2]
            lower_lines = client.ocr_lines(lower_bbox)
            # 二次 OCR 的 y 坐标是相对于子区域的，需加上偏移
            for line in lower_lines:
                line["y_center"] = line.get("y_center", 0) + (mid_y - y1)
            logger.debug(f"圣痕面板 OCR 原始行(下半区): {lower_lines}")
            # 合并去重：按 y 坐标排序，跳过与已有行 y 坐标接近的
            all_lines = list(lines)
            for ll in lower_lines:
                if not any(abs(ll.get("y_center", 0) - el.get("y_center", 0)) < 20
                           for el in all_lines):
                    all_lines.append(ll)
            all_lines.sort(key=lambda l: l.get("y_center", 0))
            lines = all_lines
            logger.debug(f"圣痕面板 OCR 合并后行数: {len(lines)}")

        # 关闭圣痕面板
        self.dm.key_press_char(hotkey)
        self._interruptible_wait(self.war3_cfg.get('general_time', 0.3))

        # 合并所有 OCR 文本
        full_text = "\n".join(line.get("text", "") for line in lines)
        logger.info(f"圣痕面板 OCR 全文: {full_text}")

        # 解析 OCR 文本
        term_limit = stigmata_cfg.get("term_limit", {})
        result = self._parse_stigmata_text(full_text, term_limit)

        logger.info(f"圣痕面板解析结果: {result}")
        return result

    # ── 辅助 ──────────────────────────────────────────────

    @staticmethod
    def _pick_upgrade_target(stats: dict, term_limit: dict):
        """选择差距最大的未达上限词条。

        :return: (pos, idx, term_name, current_val, limit_val) 或 None（全部达上限）。
        """
        best = None
        best_gap = 0.0
        for pos in ("upper", "core", "middle", "lower"):
            terms = stats.get(pos, [])
            for idx, (term_name, current_val) in enumerate(terms):
                limit_val = term_limit.get(term_name)
                if limit_val is not None and current_val < limit_val:
                    gap = limit_val - current_val
                    if gap > best_gap:
                        best_gap = gap
                        best = (pos, idx, term_name, current_val, limit_val)
        return best


def main():
    setup_global_exception_hook()
    setup_log_file("升级圣痕")
    logger.info("############################# 升级圣痕 #############################")

    task_cfg = config.load_task("war3.jiubing2.tasks.others.upgrade_stigmata")

    def task_wrapper(stop_event, progress_callback=None, progress_lines_callback=None):
        task = UpgradeStigmataTask(task_cfg)
        task.run(stop_event=stop_event, progress_lines_callback=progress_lines_callback)

    run_with_float_window(
        "升级圣痕", task_wrapper, countdown_seconds=5,
        float_cfg=task_cfg.get("float_window", {}),
    )


if __name__ == "__main__":
    main()