"""
任务基类 — 循环执行原子任务的通用逻辑。

分层设计：
- 原子任务（tasks/atomic/*）为最底层任务，可被其他任务复用；
- 个人任务成就、声望任务（黑石城/森之城）、升级圣痕等均为原子任务的下游、
  彼此同一层级，都继承 AtomicLoopTask 复用"装配公共对象 + 循环执行原子任务"的逻辑。
"""

from __future__ import annotations

import math
import time

from GameBot.inference import get_inference_client
from GameBot.runner import create_dm_client
from GameBot.runner.business.war3 import TextMonitor, War3Business
from GameBot.runner.business.war3.jiubing2 import CombatHelper, GameUI, NearbyCleaner
from GameBot.runner.tasks.war3.jiubing2.atomic import ATOMIC_TASK_REGISTRY
from GameBot.utils import StopTaskError, logger
from GameBot.utils.exception_handler import DmError

# 原子任务中预期可能发生的运行时异常（如 COM 调用失败、OCR 超时等），
# 捕获后记为失败并继续下一轮；编程错误（KeyError/TypeError 等）不在此列，直接抛出
_ATOMIC_RETRYABLE_EXC = (DmError, RuntimeError, TimeoutError, OSError)


class AtomicLoopTask:
    """循环执行某个原子任务直至完成指定次数的基类。

    子类需指定类属性：
    - atomic_task_cls：原子任务类（构造签名同 GateHarassmentTask/SwiftBeastTask）
    - atomic_name：原子任务显示名（用于日志）
    - task_config_path：本任务在 cfg 中的路径元组，如 ("war3", "jiubing2", "tasks", "achievements", "personal")
    - atomic_config_path：原子任务在 cfg 中的路径元组，如 ("war3", "jiubing2", "tasks", "atomic", "blackstone_gate_harassment")
    """

    atomic_task_cls = None  # 原子任务类（子类必须指定）
    atomic_name = "原子任务"  # 原子任务显示名（用于日志）
    task_config_path = None  # 本任务配置在 cfg 中的路径（子类必须指定）
    atomic_config_path = None  # 原子任务配置在 cfg 中的路径（子类必须指定）

    def __init__(self, cfg: dict):
        """
        :param cfg: 任务依赖闭包配置（load_task 结果，含 war3/hero/game/prompt_text 等）
        """
        self.full_cfg = cfg
        self.cfg = self._get_nested(cfg, self.task_config_path)
        self.atomic_cfg = self._get_nested(cfg, self.atomic_config_path)
        # 父级配置（子表 fallback 用，如 daily_reputation.blackstone → daily_reputation）
        self._parent_cfg = (
            self._get_nested(cfg, self.task_config_path[:-1])
            if self.task_config_path and len(self.task_config_path) > 1
            else {}
        )

        # 公共对象装配（配置均来自任务依赖闭包，不再读全局 config）
        self.dm = create_dm_client()
        war3_cfg = cfg.get("war3", {})
        hero_cfg = cfg.get("hero", {})

        self.war3 = War3Business(self.dm, war3_cfg)
        self.ui = GameUI(self.dm, war3_cfg, hero_cfg, cfg, self.war3)
        self.combat = CombatHelper(self.dm, war3_cfg, hero_cfg, cfg, self.war3)
        self.war3_cfg = war3_cfg

        # 概率清理英雄附近物品（开关 + 概率由配置控制，<=0 表示禁用）
        # 子表未配置时 fallback 到父级（如 daily_reputation.blackstone → daily_reputation）
        clear_nearby_probability = self.cfg.get(
            "clear_nearby_probability", self._parent_cfg.get("clear_nearby_probability", 0)
        )
        self.nearby_cleaner = (
            NearbyCleaner(
                self.war3,
                cfg.get("command", {}),
                probability=clear_nearby_probability,
            )
            if clear_nearby_probability > 0
            else None
        )

        # 停止信号（由 run(stop_event) 传入）
        self._stop_event = None

    @staticmethod
    def _get_nested(cfg: dict, path):
        """按路径元组从 cfg 中提取嵌套配置。"""
        if path is None:
            return {}
        node = cfg
        for key in path:
            node = node.get(key, {})
        return node

    # ── 子类可覆写的钩子 ──────────────────────────────────

    @property
    def task_name(self) -> str:
        """任务显示名（用于日志）。"""
        return self.cfg.get("name", "任务")

    def _effective_times(self) -> int:
        """实际需要执行原子任务的次数。"""
        return int(self.cfg.get("task_times", 1))

    # ── 主流程 ──────────────────────────────────────────

    def run(self, stop_event=None, progress_lines_callback=None):
        """主流程：计算轮数 → 绑定窗口 → 循环执行原子任务。

        :param stop_event: 可选的 threading.Event，设置时中断任务循环
        :param progress_lines_callback: 可选的多行进度回调，接收 List[str]
        """
        self._stop_event = stop_event
        self._progress_lines = progress_lines_callback
        times = self._effective_times()
        loop_interval = self.cfg.get("loop_interval_time", 1.5)
        logger.info(f"{self.task_name}目标次数：{times}（通过{self.atomic_name}任务完成）")

        hwnd = self.war3.find_game_window()
        if not hwnd:
            logger.error("未找到 war3 窗口")
            return

        # 尺寸调整放在绑定前：dx2 挂钩后 resize 会重建交换链导致闪屏
        self.war3.set_client_size(hwnd)
        with self.dm.bind_window(hwnd, bind_cfg=self.war3_cfg.get("bind", {})):
            # 预热 OCR 子进程（启动 + 加载 OCR 模型，约数秒），
            # 避免首次 wait_for_text 时占用超时
            get_inference_client(load_chest=False, load_combat=False)
            # 启动持续文字监测线程（整段脚本运行期间常驻，提升检测实时性）
            monitor = self._make_monitor(hwnd)
            try:
                done = self._run_loop(times, loop_interval, monitor)
            finally:
                if monitor is not None:
                    monitor.stop()

        logger.info(f"{self.task_name}结束：目标 {times} 次，成功 {done} 次")

    def _interruptible_sleep(self, seconds: float):
        """可被停止信号中断的 sleep，检测到停止时抛出 StopTaskError。"""
        if self._stop_event is not None:
            if self._stop_event.wait(seconds):
                raise StopTaskError("用户请求停止任务")
        else:
            time.sleep(seconds)

    def _make_monitor(self, hwnd: int):
        """创建持续文字监测器；子类可覆写返回 None 以禁用。"""
        atomic_task_cfg = self.full_cfg.get("atomic_task", {})
        interval = atomic_task_cfg.get("monitor_interval", 0.2)
        # 监测线程截图出错 → set stop_event 让主线程尽快中断，异常由 monitor.stop() 抛出
        monitor = TextMonitor(
            self.war3, self.full_cfg.get("prompt_text"), interval=interval, on_error=self._on_monitor_error
        )
        monitor.start(hwnd)
        return monitor

    def _on_monitor_error(self, _exc: BaseException):
        if self._stop_event is not None:
            self._stop_event.set()

    def _run_loop(self, times: int, loop_interval: float, monitor=None) -> int:
        """循环执行原子任务，返回成功次数。"""
        done = 0
        for i in range(1, times + 1):
            logger.info(f"===== 第 {i}/{times} 次{self.atomic_name}任务开始 =====")
            try:
                ok = self._run_one_atomic(monitor=monitor)
            except StopTaskError:
                if monitor is not None and monitor.error is not None:
                    raise monitor.error
                logger.info("用户请求停止，终止循环")
                break

            if ok:
                done += 1
                logger.info(f"第 {i}/{times} 次完成（累计成功 {done}）")
                self._report_progress(done, times)
            else:
                logger.warning(f"第 {i}/{times} 次失败，继续下一次")

            if i < times:
                self._interruptible_sleep(loop_interval)

        return done

    def _report_progress(self, done: int, times: int):
        """子类可覆写：报告进度到浮窗（每次原子任务成功后调用）。"""
        pass

    def _run_one_atomic(self, walk_time=None, monitor=None) -> bool:
        """执行一次原子任务，返回是否成功。

        :param walk_time: 走到任务 NPC 的等待时间覆盖（None 用 npc 配置 time）。
        :param monitor: 持续文字监测器（None 时回退到起停式 watcher）。
        """
        task = self.atomic_task_cls(
            self.dm,
            self.war3,
            self.ui,
            self.combat,
            self.atomic_cfg,
            walk_time=walk_time,
            monitor=monitor,
            nearby_cleaner=self.nearby_cleaner,
        )
        try:
            return task.run(stop_event=self._stop_event)
        except _ATOMIC_RETRYABLE_EXC as e:
            logger.error(f"{self.atomic_name}任务异常：{e}")
            return False


class ReputationTask(AtomicLoopTask):
    """声望任务基类 — 按声望上限/每次收益反推需要完成的原子任务次数。"""

    def _effective_times(self) -> int:
        target = self.cfg.get("target_reputation", 150)
        per_run = self.cfg.get("reputation_per_run", 5)
        times = math.ceil(target / per_run)
        logger.info(f"每日声望上限 {target}，每次{self.atomic_name} +{per_run}，需完成 {times} 次")
        return times

    def _report_progress(self, done: int, times: int):
        """报告声望进度到浮窗：只更新本任务对应行，保留其他行不变。"""
        if self._progress_lines is None:
            return
        per_run = self.cfg.get("reputation_per_run", 5)
        target = self.cfg.get("target_reputation", 150)
        current = min(done * per_run, target)
        label = self.cfg.get("progress_label", self.task_name)
        # 更新共享状态中本任务对应行
        state = getattr(self, "_progress_state", None)
        if state is not None:
            state[label] = f"{label}：{current}/{target}"
            self._progress_lines(list(state.values()))
        else:
            self._progress_lines([f"{label}：{current}/{target}"])

    def _build_atomic_cfg(self) -> dict:
        """根据任务级配置覆盖 points 到原子任务配置。"""
        import copy as _copy

        effective = _copy.deepcopy(self.atomic_cfg)
        points = self.cfg.get("points")
        if points:
            effective["points"] = _copy.deepcopy(points)
        return effective

    def _run_one_atomic(self, walk_time=None, monitor=None) -> bool:
        """执行一次原子任务，返回是否成功。"""
        task = self.atomic_task_cls(
            self.dm,
            self.war3,
            self.ui,
            self.combat,
            self._build_atomic_cfg(),
            walk_time=walk_time,
            monitor=monitor,
            nearby_cleaner=self.nearby_cleaner,
        )
        try:
            return task.run(stop_event=self._stop_event)
        except _ATOMIC_RETRYABLE_EXC as e:
            logger.error(f"{self.atomic_name}任务异常：{e}")
            return False


class MultiAtomicLoopTask(AtomicLoopTask):
    """多原子任务循环编排 — 接取全部 → 共享路线完成 → 依次提交。

    每轮循环：
    1. 接取阶段：依次走到各 NPC 接取任务（NPC 信息从原子任务自身配置获取）
       - 检查刷新冷却：距上次提交时间 < respawn_time 的任务跳过接取
    2. 共享路线阶段：沿 points 推进，屏幕提示完成时 -rw 查询弹窗确认
    3. 提交阶段：依次走到各 NPC，英雄在 NPC 附近自动提交
       - 提交后记录时间戳，用于下一轮冷却判断

    每次提交算 1 次任务完成，总轮数 = ceil(task_times / N)，N = atomic_tasks 数量。
    若部分任务因冷却跳过，则本轮只处理已接取的任务，并在轮间等待最短冷却时间。

    子类需指定：
    - task_config_path：本任务在 cfg 中的路径元组
    - 原子任务 key → 类的映射通过 atomic 包的 ATOMIC_TASK_REGISTRY 提供
    """

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        # 记录每个原子任务上次提交/击杀的时间戳，用于刷新冷却判断
        self._last_submit_time: dict[str, float] = {}
        self._last_kill_time: dict[str, float] = {}
        # 上一轮未完成的任务 key（仍在游戏中进行中，下轮不需要再次接取）
        self._in_progress: set[str] = set()

    def run(self, stop_event=None, progress_callback=None):
        """主流程：计算轮数 → 绑定窗口 → 循环（接取 → 共享路线 → 提交）。

        :param stop_event: 可选的 threading.Event，设置时中断任务循环
        :param progress_callback: 可选的进度回调函数，接收字符串参数
        """
        self._stop_event = stop_event
        self._progress_callback = progress_callback or (lambda text: None)
        times = int(self.cfg.get("task_times", 1))
        specs = self.cfg.get("atomic_tasks", [])
        n = len(specs)
        if n == 0:
            logger.error(f"{self.task_name}：未配置 atomic_tasks")
            return

        # 每轮不一定完成所有任务，轮数设为足够大的值，靠 done >= times 退出
        rounds = times
        loop_interval = self.cfg.get("loop_interval_time", 1.5)
        logger.info(f"{self.task_name}目标次数：{times}，每轮最多 {n} 个任务")
        self._progress_callback(f"成功 0 / {times}")

        hwnd = self.war3.find_game_window()
        if not hwnd:
            logger.error("未找到 war3 窗口")
            return

        # 尺寸调整放在绑定前：dx2 挂钩后 resize 会重建交换链导致闪屏
        self.war3.set_client_size(hwnd)
        with self.dm.bind_window(hwnd, bind_cfg=self.war3_cfg.get("bind", {})):
            get_inference_client(load_chest=False, load_combat=False)
            monitor = self._make_monitor(hwnd)
            try:
                done = self._run_multi_loop(rounds, n, loop_interval, times, monitor, hwnd)
            finally:
                if monitor is not None:
                    monitor.stop()

        logger.info(f"{self.task_name}结束：目标 {times} 次，成功 {done} 次")

    def _run_multi_loop(self, rounds: int, n: int, loop_interval: float, times: int, monitor, hwnd) -> int:
        """多原子任务主循环，返回成功提交次数。"""
        done = 0
        for r in range(1, rounds + 1):
            if done >= times:
                logger.info(f"已达目标次数 {times}，停止")
                break

            logger.info(f"===== 第 {r}/{rounds} 轮（已完成 {done} 次）=====")

            try:
                # 1. 接取全部（跳过冷却未完成的任务）
                accepted, accepted_keys = self._accept_all(hwnd)
                if accepted == 0:
                    logger.warning(f"第 {r} 轮：未接取到任何任务（可能都在冷却中）")
                    # 等待最短冷却时间后继续
                    wait = self._min_cooldown_wait()
                    if wait > 0 and r < rounds:
                        logger.info(f"等待 {wait:.0f}s 后进入下一轮")
                        self._interruptible_sleep(wait)
                    elif r < rounds:
                        self._interruptible_sleep(loop_interval)
                    continue
                # 2. 共享路线完成
                self._run_shared_route(accepted, accepted_keys, monitor, hwnd)

                # 3. 走到NPC附近，已完成的任务自动提交
                submitted = self._submit_all(accepted_keys, hwnd)
                done += submitted
            except StopTaskError:
                if monitor is not None and monitor.error is not None:
                    raise monitor.error
                logger.info("用户请求停止，终止循环")
                break

            if done > 0:
                self._progress_callback(f"成功 {done} / {times}")

            if r < rounds:
                # 等待最短冷却（任意任务可接即可开始下一轮），至少等 loop_interval
                cooldown_wait = self._min_cooldown_wait()
                wait = max(cooldown_wait, loop_interval)
                if wait > loop_interval:
                    logger.info(f"轮间等待 {wait:.0f}s")
                self._interruptible_sleep(wait)

        return done

    def _is_task_cooldown_ready(self, key: str, atomic_cfg: dict, task_cls=None) -> bool:
        """判断任务冷却是否已到，可否接取。"""
        respawn = atomic_cfg.get("respawn_time", 0)
        if respawn <= 0:
            return True
        cooldown_start = atomic_cfg.get("cooldown_start", "submit")
        if cooldown_start == "kill":
            last = self._last_kill_time.get(key)
        else:
            last = self._last_submit_time.get(key)
        if last is None:
            return True
        elapsed = time.time() - last
        if elapsed < respawn:
            label = task_cls._task_label if task_cls else key
            logger.info(f"跳过 {label}：冷却中（剩余 {respawn - elapsed:.0f}s）")
            return False
        return True

    def _min_cooldown_wait(self, accepted_keys: list = None) -> float:
        """计算最短需要等待的冷却时间（秒），0 表示有任务可接。

        只要有一个任务冷却到了就返回 0（可以开始新一轮）。
        :param accepted_keys: 本轮接取的任务key列表，仅考虑这些任务的冷却
        """
        specs = self.cfg.get("atomic_tasks", [])
        min_wait = float("inf")
        for spec in specs:
            key = spec["key"]
            if accepted_keys is not None and key not in accepted_keys:
                continue
            atomic_cfg = self._get_nested(self.full_cfg, ("war3", "jiubing2", "tasks", "atomic", key))
            respawn = atomic_cfg.get("respawn_time", 0)
            if respawn <= 0:
                return 0.0
            cooldown_start = atomic_cfg.get("cooldown_start", "submit")
            if cooldown_start == "kill":
                last = self._last_kill_time.get(key)
            else:
                last = self._last_submit_time.get(key)
            if last is None:
                return 0.0
            remaining = respawn - (time.time() - last)
            if remaining <= 0:
                return 0.0
            if remaining < min_wait:
                min_wait = remaining
        return 0.0 if min_wait == float("inf") else min_wait

    # ── 接取阶段 ──────────────────────────────────────────

    def _accept_all(self, hwnd) -> tuple:
        """依次走到各 NPC 接取任务，返回 (接取数量, 本轮任务key列表)。

        跳过以下任务：
        - 前置任务未完成（如小炎蛇需要本局完成过毒蛇）
        - 刷新冷却未到（距上次提交时间 < respawn_time）
        - 上一轮未完成仍在进行中的（不需要再次接取，直接走路线即可）

        同一 NPC 的多个任务：走到 NPC 一次 → 点击 NPC 打开对话 → 依次点技能格接取。
        """
        specs = self.cfg.get("atomic_tasks", [])

        # 按NPC分组，保留接取顺序（仅新接取的任务）
        npc_groups: dict[str, list] = {}  # npc_key -> [(task, walk_time), ...]
        npc_order: list[str] = []
        accepted_keys: list[str] = []  # 本轮所有任务（含进行中的）

        for i, spec in enumerate(specs):
            key = spec["key"]
            walk_time = spec.get("walk_time", 5)
            task_cls = ATOMIC_TASK_REGISTRY.get(key)
            if task_cls is None:
                logger.error(f"未注册的原子任务：{key}")
                continue

            # 前置任务检查（如小炎蛇需要本局完成过毒蛇）
            prereq = getattr(task_cls, "prerequisite_done", None)
            if prereq is not None and not prereq:
                logger.warning(f"跳过 {task_cls._task_label}：前置任务未完成")
                continue

            atomic_cfg = self._get_nested(self.full_cfg, ("war3", "jiubing2", "tasks", "atomic", key))

            # 刷新冷却检查（包括上一轮未完成的任务，没刷新也不走路线）
            if not self._is_task_cooldown_ready(key, atomic_cfg, task_cls):
                continue

            # 上一轮未完成的任务，仍在进行中，不需要再次接取
            if key in self._in_progress:
                accepted_keys.append(key)
                continue

            task = task_cls(
                self.dm,
                self.war3,
                self.ui,
                self.combat,
                atomic_cfg,
                walk_time=walk_time,
                nearby_cleaner=self.nearby_cleaner,
            )

            npc_key = task._npc_key
            if npc_key not in npc_groups:
                npc_groups[npc_key] = []
                npc_order.append(npc_key)
            npc_groups[npc_key].append((task, walk_time))
            accepted_keys.append(key)

        # 按NPC分组接取：每组走到NPC一次 → 点击NPC → 依次点技能格
        for npc_key in npc_order:
            group = npc_groups[npc_key]
            labels = ", ".join(t._task_label for t, _ in group)
            logger.info(f"接取NPC {npc_key} 的任务：{labels}")
            self._accept_group(group)

        # 查询弹窗确认接取数量
        total = self._check_popup(hwnd)
        return (total, accepted_keys)

    def _accept_group(self, group: list):
        """走到 NPC 一次 → 点击 NPC 打开对话 → 依次点技能格接取多个任务。

        :param group: [(atomic_task, walk_time), ...] 同一 NPC 的任务列表
        """
        gt = self.war3_cfg["general_time"]
        first_task = group[0][0]
        npc = first_task._npc
        coords = npc["coords"]
        offset = npc.get("walk_offset", [0, 0])
        walk_time = group[0][1]

        # 走到 NPC 附近
        self.dm.key_press_char("F1")
        time.sleep(gt)
        self.war3.move_to_minimap_point(
            npc["mini_coords"],
            [coords[0] + offset[0], coords[1] + offset[1]],
            mode=npc.get("walk_mode", 1),
            wait_time=walk_time,
            stop_event=self._stop_event,
        )

        # 点击 NPC 打开对话
        self.dm.move_to(*coords)
        time.sleep(gt)
        self.dm.left_click()
        time.sleep(self.war3_cfg["small_window_response_time"])

        # 依次点击技能格接取各任务
        for task, _ in group:
            grid = npc.get(task._task_grid_key, [1, 1])
            sx, sy = self.ui.get_skill_coords(grid[0], grid[1])
            self.dm.move_to(sx, sy)
            time.sleep(gt)
            self.dm.left_click()
            time.sleep(gt)

    # ── 共享路线阶段 ──────────────────────────────────────

    def _run_shared_route(self, accepted_count: int, accepted_keys: list, monitor, hwnd):
        """沿共享路线走到 NPC 附近，走完即返回（不等待任务完成）。

        :param accepted_keys: 本轮实际接取的任务 key 列表，用于过滤专属路线点
        """
        all_points = self.cfg.get("points", [])
        if not all_points:
            logger.error("未配置 points，无法执行共享路线")
            return

        # 过滤路线点：带 task 标记的专属点仅在接取了对应任务时才走
        # task 可以是字符串（单个任务）或列表（任一任务接取即走）
        points = []
        for pt in all_points:
            pt_task = pt.get("task")
            if pt_task is not None:
                if isinstance(pt_task, str):
                    pt_tasks = [pt_task]
                else:
                    pt_tasks = pt_task
                if not any(t in accepted_keys for t in pt_tasks):
                    continue
            points.append(pt)

        complete_text = self.full_cfg.get("atomic_task", {}).get("complete_text", "")
        if not complete_text:
            logger.error("未配置 atomic_task.complete_text")
            return

        # 注册完成事件监测（用于中断行走）
        complete_event = monitor.watch(complete_text)

        gt = self.war3_cfg["general_time"]

        try:
            for pt in points:
                # 定时清理英雄附近物品
                if self.nearby_cleaner is not None:
                    self.nearby_cleaner.tick()

                logger.info(f"走到：{pt['desc']}，预计 {pt['time']}s")
                self.dm.key_press_char("F1")
                time.sleep(gt)
                self.war3.move_to_minimap_point(
                    pt["mini_coords"],
                    pt["coords"],
                    mode=pt.get("walk_mode", 1),
                    wait_time=pt.get("time", 5),
                    stop_event=self._stop_event,
                )

                # 到达 kill_start 标记的路线点时，记录指定任务的击杀时间
                kill_start = pt.get("kill_start")
                if kill_start is not None:
                    now = time.time()
                    for k in kill_start:
                        self._last_kill_time[k] = now
        finally:
            monitor.unwatch(complete_event)

    # ── 提交阶段 ──────────────────────────────────────────

    def _submit_all(self, accepted_keys: list, hwnd) -> int:
        """走到 NPC 附近，已完成的任务自动提交，返回实际提交次数。

        走到 NPC 后通过弹窗查询剩余任务数，已提交 = 接取数 - 剩余数。
        全部完成时记录冷却时间戳；未完成的记入 _in_progress，下轮不再接取。
        """
        if not accepted_keys:
            self._in_progress.clear()
            return 0

        specs = self.cfg.get("atomic_tasks", [])

        # 按NPC分组，仅处理已接取的任务
        npc_groups: dict[str, tuple] = {}  # npc_key -> (task, walk_time)
        npc_order: list[str] = []
        for spec in specs:
            key = spec["key"]
            if key not in accepted_keys:
                continue
            walk_time = spec.get("walk_time", 5)
            task_cls = ATOMIC_TASK_REGISTRY.get(key)
            if task_cls is None:
                continue
            atomic_cfg = self._get_nested(self.full_cfg, ("war3", "jiubing2", "tasks", "atomic", key))
            task = task_cls(
                self.dm,
                self.war3,
                self.ui,
                self.combat,
                atomic_cfg,
                walk_time=walk_time,
                nearby_cleaner=None,
            )
            npc_key = task._npc_key
            if npc_key not in npc_groups:
                npc_groups[npc_key] = (task, walk_time)
                npc_order.append(npc_key)

        # 每个 NPC 只走一次
        for npc_key in npc_order:
            task, walk_time = npc_groups[npc_key]
            self._walk_to_npc(task, walk_time)
            time.sleep(self.war3_cfg.get("general_time", 0.5))

        # 弹窗查询：已提交的任务会从弹窗消失，弹窗中剩余的均为未提交
        # 弹窗中可能包含上一轮遗留的未提交任务（在 _in_progress 但不在本轮 accepted_keys）
        total = self._check_popup(hwnd)
        all_outstanding = set(accepted_keys) | self._in_progress
        submitted = len(all_outstanding) - total
        logger.info(f"本轮完成 {submitted} 个任务")

        # 更新进行中任务集合：carry_over 是遗留任务（肯定仍在弹窗中），
        # 剩余名额从 accepted_keys 末尾取（假设按顺序完成，靠后的可能未完成）
        carry_over = self._in_progress - set(accepted_keys)
        remaining_from_accepted = max(0, total - len(carry_over))
        self._in_progress.clear()
        self._in_progress.update(carry_over)
        if remaining_from_accepted > 0:
            self._in_progress.update(accepted_keys[-remaining_from_accepted:])

        # 毒蛇提交完成后，解锁小炎蛇（LV4）的前置要求
        if submitted > 0 and "venomous_snake" in accepted_keys:
            from GameBot.runner.tasks.war3.jiubing2.atomic.little_flame_snake import LittleFlameSnakeTask

            LittleFlameSnakeTask.prerequisite_done = True

        return submitted

    def _walk_to_npc(self, atomic_task, walk_time: float):
        """走到原子任务的 NPC 附近（用于提交）。"""
        npc = atomic_task._npc
        coords = npc["coords"]
        offset = npc.get("walk_offset", [0, 0])
        self.dm.key_press_char("F1")
        time.sleep(self.war3_cfg["general_time"])
        self.war3.move_to_minimap_point(
            npc["mini_coords"],
            [coords[0] + offset[0], coords[1] + offset[1]],
            mode=npc.get("walk_mode", 1),
            wait_time=walk_time,
            stop_event=self._stop_event,
        )

    # ── 弹窗查询 ──────────────────────────────────────────

    def _check_popup(self, hwnd) -> int:
        """发送 -rw 查询弹窗，返回弹窗中剩余任务行数。

        弹窗结构：顶部"任务"标题 → 中间 N 个任务行 → 底部"关闭"按钮。
        已提交的任务不会显示在弹窗中，因此剩余行数 = 未提交任务数。
        OCR 后顺便点击"关闭"按钮关闭弹窗。
        """
        popup_cfg = self.full_cfg.get("task_popup", {})
        command_cfg = self.full_cfg.get("command", {})

        # 发送 -rw 打开弹窗
        self.war3.send_msg(command_cfg.get("task_query", "-rw"))
        time.sleep(popup_cfg.get("open_wait_time", 0.5))

        # OCR 弹窗区域（逐行）
        area_coords = popup_cfg.get("area_coords", [600, 200, 1300, 600])
        ocr_cfg = {"area_coords": area_coords}
        lines = self.war3.ocr_lines(hwnd, ocr_cfg)

        window_kw = popup_cfg.get("window_keyword", "任务")
        close_kw = popup_cfg.get("close_keyword", "关闭")

        # 解析任务行，同时查找"关闭"按钮坐标
        task_lines = []
        close_coords = None
        for i, line in enumerate(lines):
            text = line.get("text", "")
            if i == 0 and window_kw in text:
                continue
            if close_kw in text:
                # OCR 坐标是相对截图区域的，转为客户区坐标
                ox = area_coords[0] + int(line.get("x_center", 0))
                oy = area_coords[1] + int(line.get("y_center", 0))
                close_coords = (ox, oy)
                continue
            task_lines.append(text)

        # 关闭弹窗（优先点击"关闭"按钮，兜底 Escape）
        self._close_popup(close_coords)

        if not lines:
            logger.warning("弹窗 OCR 无结果")
            return 0

        return len(task_lines)

    def _close_popup(self, close_coords: tuple = None):
        """关闭任务弹窗。

        如果配置 task_popup.close_by_x=true，则点击弹窗右上角 X 按钮；
        否则优先点击 OCR 识别到的"关闭"按钮，兜底按 Escape。

        :param close_coords: "关闭"按钮的屏幕坐标 (x, y)，为 None 时按 Escape
        """
        gt = self.war3_cfg.get("general_time", 0.3)
        popup_cfg = self.full_cfg.get("task_popup", {})

        if popup_cfg.get("close_by_x"):
            area_coords = popup_cfg.get("area_coords", [600, 200, 1300, 600])
            offset_x, offset_y = popup_cfg.get("close_offset", [15, 15])
            click_x = area_coords[2] - offset_x
            click_y = area_coords[1] + offset_y
            if click_x > 0 and click_y > 0:
                self.dm.move_to(click_x, click_y)
                time.sleep(gt)
                self.dm.left_click()
                time.sleep(gt)
                return

        if close_coords is not None and close_coords[0] > 0 and close_coords[1] > 0:
            self.dm.move_to(*close_coords)
            time.sleep(gt)
            self.dm.left_click()
            time.sleep(gt)
        else:
            self.dm.key_press_char("Escape")
            time.sleep(gt)

    def _wait_text_fade(self, monitor, text: str, max_wait: float = 6.0):
        """等待屏幕提示文本消失，避免重复触发监测。"""
        norm = self.war3._normalize_ocr(text)
        start = time.time()
        while time.time() - start < max_wait:
            if norm not in monitor.latest:
                return
            time.sleep(0.5)
