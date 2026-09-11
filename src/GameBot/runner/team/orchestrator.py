"""组队编排器 — 入口进程管理所有子进程的启动、监控和停止。

TeamOrchestrator 负责：
1. 生成 session_id
2. 为每个成员启动子进程（leader.py / follower.py）
3. 启动进度汇总线程：定期读取 progress/*.json，汇总到浮窗显示
4. 监控子进程状态（按阶段区分）：
   - KK 阶段：任何成员崩溃 → 直接重启该进程
   - 游戏阶段：同步源崩溃 → 写 exit_signal + 计入重启次数 + 重启
   - 游戏阶段：非同步源崩溃 → 仅告警不重启，其他玩家不受影响
   - 同步源重启次数超限 → 广播 stop_signal 停止全部
5. 收到停止信号时终止所有子进程
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from typing import IO, Dict, Optional

from GameBot.config import config
from GameBot.runner.team.ipc import TeamIPC
from GameBot.utils import logger


class TeamOrchestrator:
    """组队任务编排器 — 管理队长/队员子进程的生命周期。"""

    def __init__(self, cfg: dict, team_cfg: dict, stop_event: Optional[threading.Event] = None):
        """
        :param cfg: 完整任务配置闭包（load_task 结果）
        :param team_cfg: team_task 配置段
        :param stop_event: 全局停止事件
        """
        self.cfg = cfg
        self.team_cfg = team_cfg
        self.stop_event = stop_event or threading.Event()
        self.members = team_cfg.get("members", [])
        self._config_path = team_cfg.get("_config_path", "team.team_task")

        # 校验 target_player 唯一性
        target_players = [m.get("target_player", "") for m in self.members]
        seen = set()
        for tp in target_players:
            if tp in seen:
                raise ValueError(f"target_player 重复: {tp}，禁止成员中 target_player 重复")
            seen.add(tp)

        # 校验仅允许一个队长（空队伍跳过，便于测试）
        if self.members:
            leaders = [m for m in self.members if m.get("role") == "leader"]
            if len(leaders) != 1:
                raise ValueError(f"队伍必须且只能有 1 个 leader，当前为 {len(leaders)} 个")

        # 校验各成员英雄不重复（游戏不支持一局中出现多个相同英雄）
        hero_names = [m.get("hero", "") for m in self.members if m.get("hero")]
        seen_heroes = set()
        for hero in hero_names:
            if hero in seen_heroes:
                raise ValueError(f"英雄重复: {hero}，同一局中各成员必须选择不同英雄")
            seen_heroes.add(hero)

        # 同步源校验：空值或指向不存在成员时回退到队长
        sync_source_cfg = team_cfg.get("sync", {}).get("sync_source", "")
        if not sync_source_cfg or sync_source_cfg not in target_players:
            leader = next((m for m in self.members if m.get("role") == "leader"), None)
            if leader:
                self.sync_source = leader.get("target_player", "")
                if not sync_source_cfg:
                    logger.info(f"sync_source 未配置，回退到队长: {self.sync_source}")
                else:
                    logger.warning(f"sync_source '{sync_source_cfg}' 不存在于成员中，回退到队长: {self.sync_source}")
            else:
                self.sync_source = ""
                logger.warning("sync_source 回退失败：未找到队长成员")
        else:
            self.sync_source = sync_source_cfg

        # 同步源重启管理
        self._sync_source_restart_count = 0
        self._sync_source_max_restart = team_cfg.get("sync", {}).get("max_restart", 3)

        # 生成 session_id
        self.session_id = f"{int(time.time())}_{os.getpid()}"
        ipc_cfg = team_cfg.get("ipc", {})
        ipc_dir = ipc_cfg.get("ipc_dir", "logs/team_ipc")
        self.ipc = TeamIPC(self.session_id, ipc_dir)

        # 子进程管理
        self._processes: Dict[str, subprocess.Popen] = {}
        self._process_log_files: Dict[str, Optional[IO]] = {}
        self._process_lock = threading.RLock()
        self._lifecycle_event = threading.Event()
        self._progress_thread: Optional[threading.Thread] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._progress_callback = lambda text: None

        self._python_path = self._resolve_python_path()

    def set_progress_callback(self, callback) -> None:
        """设置进度回调（用于浮窗显示）。"""
        self._progress_callback = callback

    def run(self) -> None:
        """主流程：清理旧 IPC → 启动子进程 → 监控 → 等待结束 → 清理。"""
        logger.info(f"组队任务启动，session_id={self.session_id}")
        logger.info(f"同步源玩家ID: {self.sync_source}")
        logger.info(f"成员数量: {len(self.members)}")

        try:
            # 清理其他会话残留的 IPC 目录，防止污染当前任务
            self.ipc.cleanup_stale()
            # 广播初始 game_state（包含 sync_source）
            self.ipc.write_game_state(
                phase="starting",
                sync_source=self.sync_source,
                round_num=0,
            )

            # 启动子进程
            self._start_all_members()

            # 启动进度汇总线程
            self._start_progress_thread()

            # 启动子进程监控线程
            self._start_monitor_thread()

            # 等待所有子进程结束或停止信号
            while not self.stop_event.is_set() and not self._lifecycle_event.is_set():
                # 检查所有子进程是否已结束
                with self._process_lock:
                    has_processes = bool(self._processes)
                if not has_processes:
                    logger.info("所有子进程已结束")
                    break
                self.stop_event.wait(0.1)
        except KeyboardInterrupt:
            logger.info("收到中断信号，停止所有子进程")
        finally:
            self._lifecycle_event.set()
            self._stop_all_members()
            self._wait_threads()
            self.ipc.cleanup()

        logger.info("组队任务结束")

    def _resolve_python_path(self) -> str:
        """解析队长/队员子进程的 Python 解释器路径。

        队长/队员必须运行在主环境 3.12（OCR/AI 推理依赖），因此固定使用当前解释器。
        [dm].python_path 仅用于 dm_bridge 子进程，不能用于组队成员子进程。
        """
        return sys.executable

    def _open_member_log_files(self, role_key: str):
        """为子进程打开按角色区分的 stdout/stderr 日志文件。"""
        log_dir = config.project_root / "logs" / "team"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{role_key}_{self.session_id}.log"
        return open(log_path, "w", encoding="utf-8", errors="replace")

    def _close_process_resources(self, proc: subprocess.Popen, log_f=None) -> None:
        """终止仍在运行的子进程并关闭其日志文件。"""
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                logger.warning("子进程未在 3s 内退出，强制 kill")
                proc.kill()
                try:
                    proc.wait(timeout=1)
                except Exception:
                    pass
        if log_f:
            try:
                log_f.close()
            except Exception:
                pass

    def _start_all_members(self) -> None:
        """为每个成员启动子进程。"""
        src_path = str(config.project_root / "src")
        env = os.environ.copy()
        old_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{src_path}{os.pathsep}{old_pp}" if old_pp else src_path

        # 传递环境变量
        env["TEAM_SESSION_ID"] = self.session_id
        env["TEAM_CONFIG_PATH"] = self._config_path
        env["TEAM_SYNC_SOURCE"] = self.sync_source

        follower_idx = 0
        for idx, member in enumerate(self.members):
            role = member.get("role", "follower")
            if role == "leader":
                module = "GameBot.runner.team.leader"
                role_key = "leader"
            else:
                module = "GameBot.runner.team.follower"
                role_key = f"follower_{follower_idx}"
                follower_idx += 1

            env["TEAM_ROLE"] = role
            env["TEAM_MEMBER_INDEX"] = str(idx)

            cmd = [self._python_path, "-m", module]
            logger.info(f"启动子进程: {role_key}, module={module}, index={idx}")

            log_f = self._open_member_log_files(role_key)
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(config.project_root),
                    env=env,
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
            except Exception:
                log_f.close()
                raise
            with self._process_lock:
                self._process_log_files[role_key] = log_f
                self._processes[role_key] = proc

    def _start_progress_thread(self) -> None:
        """启动进度汇总线程。"""
        self._progress_thread = threading.Thread(target=self._progress_loop, daemon=True)
        self._progress_thread.start()

    def _progress_loop(self) -> None:
        """进度汇总循环：定期读取各成员进度，汇总到浮窗。"""
        interval = self.team_cfg.get("sync", {}).get("progress_report_interval", 2)
        while not self.stop_event.is_set() and not self._lifecycle_event.is_set():
            all_progress = self.ipc.read_all_progress()
            if all_progress:
                # 汇总进度文本
                lines = []
                for role, info in all_progress.items():
                    name = info.get("member_name", role)
                    progress = info.get("task_progress", "")
                    state = info.get("state", "")
                    round_num = info.get("round", 0)
                    if progress:
                        lines.append(f"[{name}] {progress}")
                    elif state:
                        lines.append(f"[{name}] {state} (R{round_num})")
                    else:
                        lines.append(f"[{name}] R{round_num}")
                summary = "\n".join(lines)
                self._progress_callback(summary)
            self._lifecycle_event.wait(interval)

    def _start_monitor_thread(self) -> None:
        """启动子进程监控线程。"""
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _monitor_loop(self) -> None:
        """监控子进程状态，按阶段区分崩溃处理。

        - KK 阶段（state=kk_phase/ready/waiting_room）：任何成员崩溃 → 直接重启该进程。
        - 游戏阶段（state=game_phase/in_game/loading）：
          - 同步源崩溃 → 写 exit_signal（让其他玩家退出游戏回到房间）+ 计入重启次数 + 重启同步源。
            重启次数超限则停止全部。
          - 非同步源崩溃 → 仅告警不重启，其他玩家继续自己的流程。
        - 未知阶段：默认直接重启。
        """
        # 构建角色→target_player 映射
        role_to_target = {}
        follower_idx = 0
        for member in self.members:
            if member.get("role") == "leader":
                role_to_target["leader"] = member.get("target_player", "")
            else:
                role_to_target[f"follower_{follower_idx}"] = member.get("target_player", "")
                follower_idx += 1

        # KK 阶段状态集合
        kk_states = {"kk_phase", "ready", "waiting_room"}
        # 游戏阶段状态集合
        game_states = {"game_phase", "in_game", "loading"}

        while not self.stop_event.is_set() and not self._lifecycle_event.is_set():
            with self._process_lock:
                processes = list(self._processes.items())
            for role_key, proc in processes:
                ret = proc.poll()
                if ret is not None:
                    target = role_to_target.get(role_key, "")
                    is_sync_source = target == self.sync_source
                    # 从进程字典移除已退出进程，避免重复处理
                    with self._process_lock:
                        if self._processes.get(role_key) is not proc:
                            continue
                        del self._processes[role_key]
                        log_f = self._process_log_files.pop(role_key, None)
                    self._close_process_resources(proc, log_f)
                    if ret == 0:
                        logger.info(f"子进程 {role_key} 正常退出")
                        continue

                    # 读取该成员最后上报的阶段
                    member_phase = self._get_member_phase(role_key)

                    if member_phase in kk_states:
                        # KK 阶段：任何成员崩溃都直接重启该进程
                        logger.error(f"子进程 {role_key} 在 KK 阶段异常退出 (返回码={ret}), 直接重启")
                        self._restart_member(role_key)

                    elif member_phase in game_states:
                        if is_sync_source:
                            # 同步源崩溃：写 exit_signal 让其他玩家退出游戏回到房间
                            self._sync_source_restart_count += 1
                            logger.error(
                                f"同步源子进程 {role_key} 在游戏阶段异常退出 (返回码={ret}), "
                                f"重启次数 {self._sync_source_restart_count}/{self._sync_source_max_restart}"
                            )
                            if self._sync_source_restart_count > self._sync_source_max_restart:
                                logger.error("同步源重启次数超限，停止全部进程")
                                self.ipc.write_stop_signal(reason="sync_source_restart_limit")
                                self.stop_event.set()
                                return
                            # 写 exit_signal，其他玩家收到后退出游戏回到房间，开始下一局
                            self.ipc.write_exit_signal(
                                round_num=self._get_current_round(),
                                reason=f"{role_key}_crashed_in_game",
                            )
                            # 重启同步源子进程
                            self._restart_member(role_key)
                        else:
                            # 非同步源崩溃：仅告警不重启
                            # 进程已退出无法接收信号，其他玩家继续自己的流程
                            # 同步源完成本局后广播 exit_signal，其他在线玩家正常退出
                            logger.warning(
                                f"非同步源子进程 {role_key} 在游戏阶段异常退出 (返回码={ret}), "
                                f"仅告警不重启，其他玩家不受影响"
                            )

                    else:
                        # 未知阶段（无进度记录或状态无法识别）：默认直接重启
                        logger.error(f"子进程 {role_key} 异常退出 (返回码={ret}, phase={member_phase}), 默认重启")
                        self._restart_member(role_key)
            self._lifecycle_event.wait(2)

    def _get_member_phase(self, role_key: str) -> str:
        """从 IPC progress 读取成员最后上报的阶段状态。

        :param role_key: 角色标识（如 "leader", "follower_0"）
        :return: 状态字符串，无记录返回空字符串
        """
        all_progress = self.ipc.read_all_progress()
        progress = all_progress.get(role_key, {})
        return progress.get("state", "")

    def _get_current_round(self) -> int:
        """从 IPC progress 中获取当前最大局号。"""
        max_round = 0
        all_progress = self.ipc.read_all_progress()
        for progress in all_progress.values():
            max_round = max(max_round, progress.get("round", 0))
        return max_round

    def _restart_member(self, role_key: str) -> None:
        """重启指定成员子进程。"""
        if self._lifecycle_event.is_set():
            return

        # 清理可能残留的同角色日志文件和旧进程（防御性）
        with self._process_lock:
            old_log_f = self._process_log_files.pop(role_key, None)
            old_proc = self._processes.pop(role_key, None)
        if old_proc:
            self._close_process_resources(old_proc, old_log_f)
        elif old_log_f:
            old_log_f.close()

        member_idx = self._role_to_index(role_key)
        if member_idx is None:
            logger.error(f"无法找到角色 {role_key} 对应的成员索引")
            return

        member = self.members[member_idx]
        role = member.get("role", "follower")
        if role == "leader":
            module = "GameBot.runner.team.leader"
        else:
            module = "GameBot.runner.team.follower"

        src_path = str(config.project_root / "src")
        env = os.environ.copy()
        old_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{src_path}{os.pathsep}{old_pp}" if old_pp else src_path
        env["TEAM_SESSION_ID"] = self.session_id
        env["TEAM_CONFIG_PATH"] = self._config_path
        env["TEAM_SYNC_SOURCE"] = self.sync_source
        env["TEAM_ROLE"] = role
        env["TEAM_MEMBER_INDEX"] = str(member_idx)

        cmd = [self._python_path, "-m", module]
        logger.info(f"重启子进程: {role_key}, module={module}, index={member_idx}")
        log_f = self._open_member_log_files(role_key)
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(config.project_root),
                env=env,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except Exception:
            log_f.close()
            raise
        if self._lifecycle_event.is_set():
            self._close_process_resources(proc, log_f)
            return
        with self._process_lock:
            self._process_log_files[role_key] = log_f
            self._processes[role_key] = proc

    def _role_to_index(self, role_key: str) -> Optional[int]:
        """角色标识转成员索引。"""
        if role_key == "leader":
            for i, m in enumerate(self.members):
                if m.get("role") == "leader":
                    return i
        else:
            # follower_N
            follower_idx = 0
            for i, m in enumerate(self.members):
                if m.get("role") != "leader":
                    if f"follower_{follower_idx}" == role_key:
                        return i
                    follower_idx += 1
        return None

    def _stop_all_members(self) -> None:
        """停止所有子进程。"""
        self._lifecycle_event.set()
        # 广播停止信号
        self.ipc.write_stop_signal(reason="orchestrator_stop")

        # 等待子进程自行退出
        grace_period = 5
        deadline = time.time() + grace_period
        # 使用快照避免与 _monitor_loop 并发修改字典
        with self._process_lock:
            processes = list(self._processes.items())
            log_files = dict(self._process_log_files)
            self._process_log_files.clear()
        for role_key, proc in processes:
            log_f = log_files.get(role_key)
            remaining = max(0, deadline - time.time())
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                logger.warning(f"子进程 {role_key} 未在 {grace_period}s 内退出，强制终止")
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
            finally:
                if log_f:
                    try:
                        log_f.close()
                    except Exception:
                        pass
        with self._process_lock:
            self._processes.clear()

    def _wait_threads(self) -> None:
        """等待辅助线程结束。"""
        if self._progress_thread and self._progress_thread.is_alive():
            self._progress_thread.join(timeout=3)
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=3)
