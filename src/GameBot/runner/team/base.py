"""组队成员基类 — 队长/队员共享的游戏阶段逻辑、进度上报、同步机制。

队长（TeamLeader）和队员（TeamFollower）继承此类，各自实现 KK 阶段逻辑。
游戏内流程由各成员的 steps 配置控制：steps 指定阶段顺序，每项可带 task_name 前缀。
"""

from __future__ import annotations

import abc
import copy
import importlib
import threading
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from GameBot.runner.driver.base import DmClientBase


def module_to_config_path(game: str, task_name: str) -> str:
    """从游戏名和任务名推导配置路径。

    例：game="war3.jiubing2", task_name="endless.endless_single"
      → "war3.jiubing2.tasks.endless.endless_single"
    """
    return f"{game}.tasks.{task_name}"


# 已知阶段名，用于解析 steps 中 "task_name.phase" 格式
_KNOWN_PHASES = {"preparation", "position_init", "run_task", "pre_exit"}


def parse_step(step_spec: str) -> tuple[str, str]:
    """解析 step_spec，返回 (task_name, phase)。

    规则：
    - 纯阶段名（如 "preparation"）→ ("", "preparation"），用默认 task 模块
    - 末尾是阶段名（如 "endless.endless_single.position_init"）→ ("endless.endless_single", "position_init")
    - 纯任务名（如 "endless.endless_single"）→ ("endless.endless_single", "run_task")
    """
    parts = step_spec.split(".")
    if len(parts) == 1 and parts[0] in _KNOWN_PHASES:
        return "", parts[0]
    if parts[-1] in _KNOWN_PHASES:
        return ".".join(parts[:-1]), parts[-1]
    return step_spec, "run_task"


from GameBot.config import ConfigurationError, apply_bind_mode, config, resolve_item_names
from GameBot.runner import create_dm_client
from GameBot.runner.business.kk import KKBusiness
from GameBot.runner.business.war3 import War3Business
from GameBot.runner.team.ipc import TeamIPC
from GameBot.utils import DmError, StopTaskError, WindowLostError, logger


class TaskContext:
    """任务上下文 — 传递给游戏内业务组件，提供任务状态属性。"""

    def __init__(self, stop_event: Optional[threading.Event] = None):
        self._stop_event = stop_event
        self._progress_callback = lambda text: None
        self.game_start_time = 0.0
        self.boss_death_time = 0.0
        self.pet_feed_time = 0.0


class TeamMemberBase(abc.ABC):
    """组队成员基类。封装游戏阶段公共逻辑、进度上报、同步机制。

    子类需实现：
    - kk_phase(round_num) -> bool: KK 阶段（建房/入房、开始游戏）
    - get_role() -> str: 角色标识（如 "leader", "follower_0"）
    """

    def __init__(
        self,
        cfg: dict,
        member_cfg: dict,
        ipc: TeamIPC,
        sync_source: str,
        stop_event: Optional[threading.Event] = None,
    ):
        """
        :param cfg: 完整任务配置闭包（load_task 结果）
        :param member_cfg: 当前成员配置（members 数组中的一项）
        :param ipc: TeamIPC 实例
        :param sync_source: 同步源玩家 ID（target_player）
        :param stop_event: 全局停止事件
        """
        self.task_cfg = cfg
        self.member_cfg = member_cfg
        self.ipc = ipc
        self.sync_source = sync_source
        self.stop_event = stop_event or threading.Event()
        self.dm = self._create_dm()

        # 合并 player_id → target_player（War3 窗口归属玩家 ID）
        self.target_player = member_cfg.get("target_player", "")
        self.is_sync_source = self.target_player == sync_source

        # 组队任务配置
        team_cfg = cfg.get("team", {}).get("team_task", {})
        self._team_cfg = team_cfg
        self._game = team_cfg.get("game", "")
        self._total_rounds = team_cfg.get("rounds", 0)
        # 成员步骤编排（必填）
        # steps 中每项可以是：
        #   "phase"                         — 通用阶段，沿用上一个显式 task 模块调用
        #   "task_name.phase"               — 指定任务模块的阶段（如 "others.fishing.position_init"）
        #   "task_name"                     — 等同于 "task_name.run_task"（如 "others.fishing"）
        #   task_name 是游戏模块下的相对路径（如 "endless.endless_single"、"others.fishing"）
        self._steps = member_cfg.get("steps", [])
        if not self._steps:
            self._steps = ["preparation", "position_init", "run_task", "pre_exit"]
        # 解析 steps 中涉及的 task_name，供 _execute_steps 维护当前默认 task
        self._task_names_in_steps = []
        for s in self._steps:
            tn, _ = parse_step(s)
            if tn and tn not in self._task_names_in_steps:
                self._task_names_in_steps.append(tn)

        # 组队模式英雄按成员显式配置加载（防止多开选择同一英雄）
        self._load_member_hero(cfg, member_cfg)

        # 组队模式物品栏最高优先级：member_cfg 中的 inventory 覆盖 hero 配置
        member_inventory = member_cfg.get("inventory")
        if member_inventory:
            if "hero" not in cfg:
                cfg["hero"] = {}
            cfg["hero"]["inventory"] = member_inventory
            # 解析物品名为 item_id（支持用 item = "物品名" 替代 item_id = 数字）
            resolve_item_names(member_inventory, cfg.get("war3", {}).get("jiubing2", {}).get("items", []))

        # 组队模式格子快捷键覆盖：member_cfg 中的 inventory_slots 覆盖 kk 默认配置
        member_slots = member_cfg.get("inventory_slots")
        if member_slots:
            if "hero" not in cfg:
                cfg["hero"] = {}
            cfg["hero"]["inventory_slots"] = member_slots

        # bind_mode 决定绑定配置：foreground（前台）或 background（后台）
        # 多成员组队强制后台（bind_background），单成员按配置选择
        bind_mode = team_cfg.get("bind_mode", "foreground")
        members = team_cfg.get("members", [])
        use_background = bind_mode == "background" or len(members) > 1

        war3_cfg = cfg.get("war3", {})
        hero_cfg = cfg.get("hero", {})
        kk_cfg = cfg.get("kk", {})

        # 多成员时强制后台绑定（与 load_task 共用同一套派生逻辑）
        if use_background:
            apply_bind_mode(cfg, force_mode="background")

        self.war3 = self._create_war3(war3_cfg)
        self.kk = self._create_kk(kk_cfg)

        # 超时配置来源 TOML
        self._war3_window_timeout = war3_cfg.get("wait_for_game_window", {}).get("timeout", 60)

        self.war3_cfg = war3_cfg
        self.hero_cfg = hero_cfg
        self.kk_cfg = kk_cfg

        # 任务上下文
        self.task_ctx = TaskContext(self.stop_event)
        self.task_ctx._progress_callback = self._on_task_progress

        # 进度上报
        self._last_progress_time = 0.0
        self._last_progress_state = ""
        self._progress_interval = team_cfg.get("sync", {}).get("progress_report_interval", 2)

        # exit_signal 监控线程（非同步源在 task_module 执行期间启动）
        self._exit_signal_watcher = None
        self._exit_signal_watcher_running = False

        # 当前局数，leader/follower 统一以 room_info.round 为权威
        self._current_round = 1

        # 队长局号恢复一次性标志：仅进程启动后首次循环执行，避免 KK 失败重试时误升局号
        self._round_recovered = False

        # 重启后无条件接受首条 room_info（避免 leader 局号回退死锁）
        self._accept_any_room_info = False

        # 本成员所属 KK 大厅窗口与进程 PID（多开时避免操作其他账号窗口）
        self.hall_hwnd = 0
        self.owner_pid = 0

        # 全局停止信号监控
        self._signal_watcher = None
        self._signal_watcher_running = False
        self._stop_requested = False
        self._exit_signal_received = False

        # 当前 War3 窗口句柄（_game_phase 中赋值，供 _safe_quit_game 使用）
        self._current_war3_hwnd = 0

    # ---------- 工厂方法（子类或测试可覆盖以注入 mock） ----------

    def _create_dm(self) -> "DmClientBase":
        """创建大漠驱动实例（按环境自动选择 local/bridge）。"""
        return create_dm_client()

    def _create_war3(self, war3_cfg: dict) -> "War3Business":
        """创建 War3 业务对象。"""
        return War3Business(self.dm, war3_cfg)

    def _create_kk(self, kk_cfg: dict) -> "KKBusiness":
        """创建 KK 业务对象。"""
        return KKBusiness(self.dm, kk_cfg)

    def _load_member_hero(self, cfg: dict, member_cfg: dict) -> None:
        """按成员配置显式加载英雄，替换任务默认英雄。

        组队模式下同一局不能出现多个相同英雄，因此允许在成员配置中显式
        指定 hero，覆盖 steps 中任务依赖所引入的默认英雄。

        :param cfg: 已合并的完整任务配置（将被原地修改）
        :param member_cfg: 当前成员配置（members 数组中的一项）
        """
        member_hero = member_cfg.get("hero")
        if not member_hero or not self._game:
            return

        hero_config_name = f"{self._game}.heroes.{member_hero}"
        try:
            hero_raw = config._load_file(hero_config_name)
        except ConfigurationError:
            logger.warning(f"成员 {self.target_player} 指定的英雄配置 {hero_config_name} 不存在，使用任务依赖默认英雄")
            return

        inheritable, _ = config._split_sections(hero_raw)
        if "hero" not in inheritable:
            logger.warning(f"英雄配置 {hero_config_name} 中未找到 [hero] 节点")
            return

        # 用成员指定英雄的完整 [hero] 配置替换当前 hero（避免与默认英雄混合）
        cfg["hero"] = copy.deepcopy(inheritable["hero"])
        logger.info(f"成员 {self.target_player} 使用英雄: {member_hero}")

    # ---------- 子类需实现 ----------

    @abc.abstractmethod
    def get_role(self) -> str:
        """返回角色标识（如 "leader", "follower_0"）。"""
        ...

    @abc.abstractmethod
    def kk_phase(self, round_num: int) -> bool:
        """KK 阶段：建房/入房、等待准备、开始游戏。

        :param round_num: 当前局数
        :return: True=成功进入游戏, False=失败需重试
        """
        ...

    # ---------- 公共逻辑 ----------

    def run(self) -> None:
        """主循环：KK 阶段 → 游戏阶段 → 同步 → 下一局。"""
        consecutive_failures = 0
        safe_stop_threshold = (
            self.task_cfg.get("team", {}).get("team_task", {}).get("sync", {}).get("safe_stop_threshold", 0)
        )
        self._start_signal_watcher()
        try:
            while True:
                try:
                    # 处理由 watcher 设置的停止请求
                    if self._stop_requested:
                        logger.info("收到停止信号，退出")
                        break

                    # 检查总局数限制（在 KK 阶段之前，避免进入不必要的建房阶段）
                    if self._total_rounds > 0 and self._current_round > self._total_rounds:
                        logger.info(f"已达总局数 {self._total_rounds}，任务完成")
                        break

                    # 检查全局停止信号
                    if self.ipc.read_stop_signal():
                        logger.info("收到全局停止信号，退出")
                        break

                    # 队长首次进入 KK 阶段前，尝试从 IPC 恢复局号（仅执行一次）
                    if self.get_role() == "leader" and not self._round_recovered:
                        self._round_recovered = True
                        self._recover_round()

                    # KK 阶段
                    self._report_progress(state="kk_phase", round_num=self._current_round)
                    if not self.kk_phase(self._current_round):
                        if self._stop_requested:
                            continue
                        logger.error(f"第 {self._current_round} 局 KK 阶段失败，跳过本局")
                        consecutive_failures += 1
                        if safe_stop_threshold > 0 and consecutive_failures >= safe_stop_threshold:
                            logger.error(f"连续失败 {consecutive_failures} 次达到阈值 {safe_stop_threshold}，安全停止")
                            self.ipc.write_stop_signal(reason="consecutive_failures")
                            break
                        # KK 阶段失败不递增局数，等待新的 room_info 重试同一局
                        continue

                    # 游戏阶段
                    self._report_progress(state="game_phase", round_num=self._current_round)
                    game_failed = self._game_phase(self._current_round)

                    # 同步退出
                    self._sync_exit(self._current_round)

                    # 非同步源收到同步源信号后退出 War3
                    if not self.is_sync_source and self._current_war3_hwnd:
                        logger.info("非同步源收到同步源退出信号，退出 War3")
                        self._safe_quit_game()
                    if self._exit_signal_received and not self._stop_requested:
                        self._exit_signal_received = False
                        self.stop_event.clear()

                    # exit_signal 采用 round 纪元语义，由新一局 room_info(round+1) 自然失效，
                    # 不再由消费者删除，避免多消费者竞态空等。

                    consecutive_failures = consecutive_failures + 1 if game_failed else 0
                    if safe_stop_threshold > 0 and consecutive_failures >= safe_stop_threshold:
                        logger.error(f"连续失败 {consecutive_failures} 次达到阈值 {safe_stop_threshold}，安全停止")
                        self.ipc.write_stop_signal(reason="consecutive_failures")
                        break
                    self._current_round += 1

                except StopTaskError:
                    if self._exit_signal_received:
                        # 同步源退出信号中断了游戏内任务，退出游戏并继续下一局
                        logger.info("收到同步源退出信号，退出游戏回到房间，继续下一局")
                        self._exit_signal_received = False
                        self._safe_quit_game()
                        self._current_round += 1
                        self.stop_event.clear()
                        continue
                    elif self._stop_requested:
                        logger.info("收到停止信号，退出组队任务")
                    else:
                        logger.info("收到停止信号，退出组队任务")
                    break

        except Exception as e:
            logger.error(f"组队任务异常退出: {e}")
            raise
        finally:
            self._stop_signal_watcher()
            self._report_progress(state="stopped", round_num=self._current_round)

    def _game_phase(self, round_num: int) -> bool:
        """游戏阶段：等待窗口 → 绑定 → 执行步骤列表 → 退出游戏。

        每个成员的 steps 配置控制游戏内流程，支持不同任务编排。

        :return: True=本局失败, False=本局正常完成
        """
        logger.debug("等待游戏窗口")
        # 提取所有成员的玩家名，供 War3 窗口归属识别时拆分 OCR 拼接的文本
        all_members = self._team_cfg.get("members", [])
        known_players = [m.get("target_player", "") for m in all_members if m.get("target_player")]
        hwnd = self.war3.bind_war3_window(
            target_player=self.target_player,
            stop_event=self.stop_event,
            timeout=self._war3_window_timeout,
            known_players=known_players,
        )
        if not hwnd:
            logger.error("未找到游戏窗口，跳过本局")
            self._handle_kk_disconnect()
            return True

        self._current_war3_hwnd = hwnd
        flow_failed = False
        try:
            # 绑定前验证窗口仍然有效（War3 可能在此期间崩溃）
            if not self._is_window_alive(hwnd):
                logger.error("War3 窗口在绑定前已消失，可能已崩溃")
                self.dm.save_screenshot(label="war3_window_lost_before_bind", force=True)
                self._handle_kk_disconnect()
                return True
            with self.dm.bind_window(hwnd, bind_cfg=self.war3_cfg.get("bind", {})):
                # 等待进入游戏
                self._wait_enter_game()
                # 上报已进入游戏
                self._report_progress(state="in_game", round_num=round_num)
                # 队长等待所有队员均进入游戏（开始游戏屏障），避免队员准备后队长提前退出
                if self.get_role() == "leader":
                    self._wait_all_members_in_game()
                # 执行步骤列表
                flow_failed = self._execute_steps(round_num)
                # 退出游戏（在绑定窗口内，无需重新绑定）
                # 非同步源不主动退出 War3，等待同步源退出信号后再退出
                if self.is_sync_source:
                    self.war3.quit_game()
                    self._current_war3_hwnd = 0
                else:
                    logger.info("非同步源等待同步源退出信号")
        except WindowLostError:
            logger.error("掉线，游戏窗口消失")
            self.dm.save_screenshot(label="war3_window_lost", force=True)
            self._handle_kk_disconnect()
            return True
        except TimeoutError as e:
            logger.error(f"卡在加载界面: {e}")
            self.dm.save_screenshot(label="war3_enter_game_timeout", force=True)
            self.war3.quit_game()
            self._current_war3_hwnd = 0
            return True
        except DmError as e:
            logger.error(f"游戏阶段大漠操作异常: {e}")
            self.dm.save_screenshot(label="war3_dm_error", force=True)
            self._current_war3_hwnd = 0
            return True

        return flow_failed

    def _wait_enter_game(self) -> None:
        """等待游戏加载完成（子类可覆盖，默认使用 War3Business 的通用等待）。"""
        self.war3.wait_enter_game(self.task_ctx, self.stop_event)

    def _execute_steps(self, round_num: int) -> bool:
        """执行成员的任务阶段列表。

        steps 中每项可以是：
        - "phase" — 通用阶段，沿用上一个显式 task 模块调用
        - "task_name.phase" — 指定任务模块的阶段
        - "task_name" — 等同于 "task_name.run_task"
        任一步骤失败（member._flow_failed=True）则跳过剩余。
        非同步源在步骤执行期间启动 exit_signal 监控线程。

        :return: True=流程失败, False=流程正常完成
        """
        self._current_round = round_num
        self._flow_failed = False

        if not self._steps:
            logger.error("未配置 steps 阶段列表")
            self._flow_failed = True
            return True

        # 非同步源在步骤执行期间轮询 exit_signal
        if not self.is_sync_source:
            self._start_exit_signal_watcher()
        # 当前 task 名称：初始化为 steps 中第一个显式 task，随后每一步更新
        current_task_name = self._task_names_in_steps[0] if self._task_names_in_steps else ""
        try:
            for step_spec in self._steps:
                if self.stop_event.is_set() or self._flow_failed:
                    break
                task_name, phase = parse_step(step_spec)
                if not task_name:
                    # 纯 phase，沿用上一个显式 task 模块
                    task_name = current_task_name
                else:
                    # 显式 task 名，更新当前步骤上下文
                    current_task_name = task_name
                self._invoke_step(task_name, phase)
        except StopTaskError:
            raise
        except Exception as e:
            logger.error(f"步骤执行异常: {e}")
            self._flow_failed = True
        finally:
            if not self.is_sync_source:
                self._stop_exit_signal_watcher()

        return self._flow_failed

    def _invoke_step(self, task_name: str, phase: str) -> None:
        """执行单个任务阶段。

        :param task_name: 任务相对路径（如 "endless.endless_single"、"others.fishing"）
        :param phase: 阶段名（如 "preparation", "position_init", "run_task", "pre_exit"）
        """
        # 推导模块路径：GameBot.runner.tasks.{game}.{task_name}
        module_path = f"GameBot.runner.tasks.{self._game}.{task_name}"

        # 动态导入并调用
        try:
            module = importlib.import_module(module_path)
            func = getattr(module, phase, None)
            if func is None or not callable(func):
                logger.error(f"任务模块 {module_path} 无可调用方法 {phase}")
                self._flow_failed = True
                return
            logger.info(f"调用 {task_name}.{phase}()")
            func(self, self.stop_event)
        except StopTaskError:
            raise
        except Exception as e:
            logger.error(f"{task_name}.{phase}() 执行异常: {e}")
            self._flow_failed = True

    def _sync_exit(self, round_num: int) -> None:
        """同步退出逻辑：同步源广播退出信号，非同步源等待信号。

        非同步源持续等待 exit_signal（按 round 纪元过滤），直到收到信号或 stop_event。
        无需超时：同步源正常完成后会广播 exit_signal；若同步源崩溃，
        orchestrator 会广播 exit_signal，exit_signal_watcher 会中断当前等待。
        """
        if self.is_sync_source:
            logger.info(f"本成员是同步源，广播退出信号 (round={round_num})")
            self.ipc.write_exit_signal(round_num, reason="task_complete")
        else:
            logger.info(f"本成员非同步源，等待退出信号 (round={round_num})")
            poll_interval = 0.5
            while not self.stop_event.is_set():
                if self.ipc.read_exit_signal(timeout=poll_interval, poll_interval=poll_interval, min_round=round_num):
                    logger.info(f"收到退出信号 (round={round_num})")
                    return
            logger.info("等待退出信号时收到停止事件，提前退出")

    def _start_exit_signal_watcher(self) -> None:
        """启动后台线程轮询 exit_signal，收到时设置 stop_event 中断 task_module。"""
        if self._exit_signal_watcher is not None:
            return
        self._exit_signal_watcher = threading.Thread(target=self._exit_signal_watch_loop, daemon=True)
        self._exit_signal_watcher_running = True
        self._exit_signal_watcher.start()

    def _stop_exit_signal_watcher(self) -> None:
        """停止 exit_signal 轮询线程。"""
        self._exit_signal_watcher_running = False
        if self._exit_signal_watcher is not None:
            self._exit_signal_watcher.join(timeout=3)
            self._exit_signal_watcher = None

    def _exit_signal_watch_loop(self) -> None:
        """轮询 exit_signal，收到 round >= 当前局的信号时中断当前 task_module。

        设置 _exit_signal_received 标志 + stop_event，让 run() 区分这是
        同步源退出信号（应退出游戏继续下一局）而非全局停止信号。
        """
        poll_interval = 1.0
        while self._exit_signal_watcher_running and not self.stop_event.is_set():
            signal = self.ipc.read_exit_signal(
                timeout=0,
                poll_interval=poll_interval,
                min_round=self._current_round,
            )
            if signal:
                logger.info(f"在 task_module 执行期间收到 exit_signal (round={signal.get('round')})，中断任务")
                self._exit_signal_received = True
                self.stop_event.set()
                return
            self.stop_event.wait(poll_interval)

    # ---------- 全局 stop/restart 信号监控 ----------

    def _start_signal_watcher(self) -> None:
        """启动 stop 信号监控线程。"""
        if self._signal_watcher is not None:
            return
        self._signal_watcher = threading.Thread(target=self._signal_watch_loop, daemon=True)
        self._signal_watcher_running = True
        self._signal_watcher.start()

    def _stop_signal_watcher(self) -> None:
        """停止 stop 信号监控线程。"""
        self._signal_watcher_running = False
        if self._signal_watcher is not None:
            self._signal_watcher.join(timeout=1)
            self._signal_watcher = None

    def _signal_watch_loop(self) -> None:
        """轮询 stop_signal，收到后中断当前流程。

        - stop_signal: 设置 _stop_requested + stop_event，成员优雅退出。

        节拍使用 time.sleep 而非 stop_event.wait，避免 stop_event 置位后 watcher 自旋。
        """
        poll_interval = 0.2
        while self._signal_watcher_running:
            if self.ipc.read_stop_signal():
                self._stop_requested = True
                logger.info("收到全局停止信号")
                self.stop_event.set()
                return
            time.sleep(poll_interval)

    def _wait_all_members_in_game(self, timeout: Optional[float] = None) -> bool:
        """队长进入游戏后等待所有队员均上报 in_game 状态。

        通过读取 progress/*.json 实现开始游戏屏障，避免队长提前退出导致队员被落下。
        放行条件：成员 state == "in_game" 且 round == 当前局，防止陈旧进度误放行。
        已死亡成员（state == "stopped" 或 timestamp 过期）自动跳过，避免每局等满超时。

        :param timeout: 超时秒数，未提供时从 team_cfg.sync.in_game_wait_timeout 读取
        :return: True=所有存活成员均进入游戏, False=超时
        """
        team_cfg = self.task_cfg.get("team", {}).get("team_task", {})
        if timeout is None:
            timeout = team_cfg.get("sync", {}).get("in_game_wait_timeout", 60)

        # 获取当前成员角色集合
        members_cfg = team_cfg.get("members", [])
        expected_roles = set()
        follower_idx = 0
        for member in members_cfg:
            role = member.get("role", "follower")
            if role == "leader":
                expected_roles.add("leader")
            else:
                expected_roles.add(f"follower_{follower_idx}")
                follower_idx += 1
        if not expected_roles:
            return True

        # 陈旧进度阈值：超过 3 倍超时未上报视为已死亡成员
        stale_threshold = timeout * 3
        skipped_roles: set = set()

        start = time.time()
        while time.time() - start < timeout:
            if self.stop_event.is_set():
                return False

            now = time.time()
            all_progress = self.ipc.read_all_progress()
            in_game_roles = set()
            for role, progress in all_progress.items():
                state = progress.get("state", "")
                prog_round = progress.get("round", 0)
                ts = progress.get("timestamp", 0)
                # 已停止的成员直接跳过
                if state == "stopped":
                    if role not in skipped_roles:
                        logger.info(f"成员 {role} 已停止，跳过屏障等待")
                        skipped_roles.add(role)
                    continue
                # timestamp 过期的成员视为已死亡，跳过
                if ts and (now - ts) > stale_threshold:
                    if role not in skipped_roles:
                        logger.warning(f"成员 {role} 进度过期 ({now - ts:.0f}s)，跳过屏障等待")
                        skipped_roles.add(role)
                    continue
                # 放行条件：state == in_game 且 round 匹配当前局
                if state == "in_game" and prog_round == self._current_round:
                    in_game_roles.add(role)

            # 期望角色中减去已跳过的死亡成员
            waiting_roles = expected_roles - skipped_roles
            if waiting_roles.issubset(in_game_roles):
                logger.info(f"所有存活成员已进入游戏: {sorted(waiting_roles)}")
                return True

            time.sleep(0.5)

        logger.warning(f"等待所有成员进入游戏超时 ({timeout}s)")
        self.dm.save_screenshot(label="wait_all_members_in_game_timeout", force=True)
        return False

    def _claim_hall_window(self) -> bool:
        """认领属于 target_player 的 KK 大厅窗口，缓存 hall_hwnd 与 owner_pid。

        未配置 target_player 或多开场景下大厅被隐藏时可能失败。
        首次认领失败时重试一次（OCR 可能因界面动画偶发失败）。
        若已认领且窗口仍有效（PID 一致），则复用缓存避免每局重复 OCR 认领。
        """
        if not self.target_player:
            logger.warning("未配置 target_player，无法精确认领 KK 大厅窗口")
            return False
        # 缓存复用：窗口仍有效且 PID 一致时跳过重复认领
        if self.hall_hwnd and self.owner_pid:
            try:
                pid = self.dm.get_window_process_id(self.hall_hwnd)
                if pid == self.owner_pid:
                    logger.debug(f"复用已认领的大厅窗口: hwnd={self.hall_hwnd}, pid={self.owner_pid}")
                    return True
            except (DmError, OSError):
                pass
            # 窗口已失效，清空缓存
            self.hall_hwnd = 0
            self.owner_pid = 0
        # 首次尝试
        for attempt in range(1, 3):
            try:
                hall_hwnd, owner_pid = self.kk.claim_hall_window(
                    self.dm,
                    self.target_player,
                    stop_event=self.stop_event,
                    hall_owner_cache=self.ipc,
                )
                if hall_hwnd:
                    self.hall_hwnd = hall_hwnd
                    self.owner_pid = owner_pid
                    logger.debug(f"已保存大厅认领结果: hwnd={hall_hwnd}, pid={owner_pid}")
                    return True
            except StopTaskError:
                return False
            except (DmError, OSError, RuntimeError) as e:
                logger.warning(f"认领大厅窗口异常 (尝试 {attempt}/2): {e}")
            if attempt < 2:
                logger.info("等待 2s 后重试认领大厅窗口")
                if self.stop_event.wait(2):
                    return False
        # 多开场景下认领失败会导致 PID 过滤全链路失效，升级为 error 便于排查
        members = self.task_cfg.get("team", {}).get("team_task", {}).get("members", [])
        if len(members) > 1:
            logger.error(f"多开场景下认领大厅窗口失败，PID 过滤将失效 (target_player={self.target_player})")
        return False

    def _recover_round(self) -> None:
        """队长重启时从 IPC 进度/游戏状态恢复局号，避免从 round=1 建房导致死锁。"""
        if self.get_role() != "leader":
            return
        try:
            max_round = 0
            game_state = self.ipc.read_game_state()
            if game_state:
                max_round = max(max_round, game_state.get("round", 0))
            all_progress = self.ipc.read_all_progress()
            for progress in all_progress.values():
                max_round = max(max_round, progress.get("round", 0))
            if max_round > 0:
                # 崩溃后保守策略：从最大已记录局号 + 1 开始，避免重复同一 round
                self._current_round = max_round + 1
                logger.info(f"队长从 IPC 恢复局号: {self._current_round}")
        except (DmError, OSError, RuntimeError) as e:
            logger.warning(f"恢复局号失败: {e}")

    def _is_window_alive(self, hwnd: int) -> bool:
        """检查窗口是否仍然有效（窗口存在且进程未退出）。

        :param hwnd: 窗口句柄
        :return: True=窗口有效, False=窗口已消失或进程已退出
        """
        if not hwnd:
            return False
        try:
            if not self.dm.get_window_state(hwnd, 0):
                return False
            pid = self.dm.get_window_process_id(hwnd)
            if pid == 0:
                return False
            # 大漠 GetProcessInfo 失败或返回空表示进程已不存在
            info = self.dm.get_process_info(pid)
            return bool(info and "|" in info)
        except Exception:
            return False

    def _safe_quit_game(self) -> None:
        """安全退出游戏（忽略异常）。

        watcher 触发 restart 时可能在 _game_phase 的 with 块内（已绑定），
        也可能在 with 块外（已解绑），因此自行绑定后退出。
        """
        hwnd = self._current_war3_hwnd
        if not hwnd:
            return
        if not self._is_window_alive(hwnd):
            logger.warning(f"War3 窗口 hwnd={hwnd} 已失效，跳过退出游戏")
            self._current_war3_hwnd = 0
            return
        try:
            with self.dm.bind_window(hwnd, bind_cfg=self.war3_cfg.get("bind", {})):
                self.war3.quit_game()
        except (DmError, OSError) as e:
            logger.warning(f"退出游戏时异常: {e}")
        finally:
            self._current_war3_hwnd = 0

    def _close_stale_war3_window(self) -> None:
        """关闭残留的 War3 窗口（KK 阶段不应存在游戏窗口）。

        如果 _current_war3_hwnd 仍有效，尝试退出游戏；如果窗口已失效，
        尝试枚举并关闭所有 War3 窗口。最后清空 _current_war3_hwnd。
        """
        if self._current_war3_hwnd:
            logger.warning(f"KK 阶段检测到残留 War3 窗口 hwnd={self._current_war3_hwnd}，尝试关闭")
            self._safe_quit_game()
            return
        # 枚举所有 War3 窗口并关闭
        war3_class = self.war3_cfg.get("window_class", "")
        war3_title = self.war3_cfg.get("window_title", "")
        if not war3_class:
            return
        wins = self.dm.find_windows(war3_class, war3_title)
        if not wins:
            return
        for w in wins:
            hwnd = w["hwnd"]
            logger.warning(f"KK 阶段发现残留 War3 窗口 hwnd={hwnd}，尝试关闭")
            try:
                self.dm.set_window_state(hwnd, 0)
            except Exception as e:
                logger.warning(f"关闭 War3 窗口 hwnd={hwnd} 失败: {e}")
        time.sleep(1)

    def _handle_kk_disconnect(self) -> None:
        """检测并处理 KK 掉线重连弹窗（多开时通过 PID 过滤）。"""
        self.kk.handle_disconnect_dialog(self.dm, owner_pid=self.owner_pid)

    # ---------- 进度上报 ----------

    def _on_task_progress(self, text: str) -> None:
        """任务内部进度回调（如 EndlessRunner 的楼层/局数）。"""
        self._report_progress(
            state="in_game",
            round_num=self._current_round,
            task_progress=text,
        )

    def _report_progress(
        self,
        state: str = "",
        round_num: int = 1,
        task_progress: str = "",
    ) -> None:
        """通过 IPC 上报自身进度。

        节流仅作用于同状态的重复上报；状态转换（state 与上次不同）时强制写入，
        确保 in_game/stopped 等关键状态及时落盘，避免屏障误判。
        """
        now = time.time()
        is_state_change = state != self._last_progress_state
        if not is_state_change and now - self._last_progress_time < self._progress_interval and task_progress == "":
            return
        self._last_progress_time = now
        self._last_progress_state = state

        self.ipc.write_progress(
            role=self.get_role(),
            member_name=self.target_player,
            task_name=self._get_task_name(),
            task_progress=task_progress,
            state=state,
            round_num=round_num,
        )

    # ---------- 辅助 ----------

    def _get_task_name(self) -> str:
        """从 steps 中提取任务描述（用于进度上报）。"""
        return " → ".join(self._task_names_in_steps)

    def _interruptible_wait(self, seconds: float) -> None:
        """可被停止信号中断的等待。"""
        if self.stop_event.wait(seconds):
            raise StopTaskError("用户请求停止任务")


def load_member_config():
    """子进程入口公共配置加载 — 从环境变量读取参数，加载配置，返回所需对象。

    leader.py 和 follower.py 的 main() 调用此函数获取公共配置，
    避免重复代码。返回 None 表示配置加载失败，调用方应直接 return。
    """
    import copy
    import os
    import threading

    from GameBot.config import config
    from GameBot.runner.team.ipc import TeamIPC
    from GameBot.utils.exception_handler import setup_global_exception_hook

    setup_global_exception_hook()

    session_id = os.environ.get("TEAM_SESSION_ID", "")
    config_path = os.environ.get("TEAM_CONFIG_PATH", "team.team_task")
    sync_source = os.environ.get("TEAM_SYNC_SOURCE", "")
    member_index = int(os.environ.get("TEAM_MEMBER_INDEX", "0"))

    if not session_id:
        logger.error("缺少 TEAM_SESSION_ID 环境变量")
        return None

    # 加载团队配置
    team_cfg_result = config.load_task(config_path)
    team_cfg = team_cfg_result.get("team", {}).get("team_task", {})
    members = team_cfg.get("members", [])
    if member_index >= len(members):
        logger.error(f"成员索引 {member_index} 超出范围（共 {len(members)} 个成员）")
        return None

    member_cfg = members[member_index]

    # 从 steps 解析涉及的 task_name，通过 game + task_name 推导配置路径自动加载
    game = team_cfg.get("game", "")
    steps = member_cfg.get("steps", [])
    config_paths = []
    for s in steps:
        tn, _ = parse_step(s)
        if tn:
            tcp = module_to_config_path(game, tn)
            if tcp not in config_paths:
                config_paths.append(tcp)

    cfg = copy.deepcopy(team_cfg_result)
    for tcp in config_paths:
        task_cfg_result = config.load_task(tcp)
        config._deep_merge(cfg, task_cfg_result)
    if config_paths:
        logger.info(f"已从 steps 自动加载任务配置: {config_paths}")
    else:
        logger.warning("steps 未解析出任何任务配置路径，使用团队配置（英雄/物品栏可能不正确）")

    ipc_cfg = team_cfg.get("ipc", {})
    ipc_dir = ipc_cfg.get("ipc_dir", "logs/team_ipc")
    ipc = TeamIPC(session_id, ipc_dir)

    stop_event = threading.Event()

    return {
        "cfg": cfg,
        "team_cfg": team_cfg,
        "member_cfg": member_cfg,
        "ipc": ipc,
        "sync_source": sync_source,
        "member_index": member_index,
        "stop_event": stop_event,
    }
