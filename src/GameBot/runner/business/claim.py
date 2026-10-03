"""统一窗口认领原语 — claim_window。

war3 / KK 房间 / KK 大厅收敛到同一认领骨架：

    缓存复用（hwnd 存活 + 归属复核一致）→ 枚举候选 → IsWindow/最小化过滤 →
    per-hwnd 命名互斥锁 → owner 判定（只读 PID/PPID 查表）→
    未知时可选 identify 回调自举 → 匹配持锁登记注册表 / 不匹配释放 →
    超时抛 ClaimError 终止任务。

全局认领串行锁已退役：per-hwnd 互斥锁 + 注册表完成多脚本协调。
单开快速路径：注册表存活实例数==1 且候选数==1 时跳过 owner 判定直接
持锁登记（仍持有互斥锁，防晚加入脚本抢占同一窗口）。

归属判定全程只读（IsWindow/GetWindowThreadProcessId/Toolhelp32），
不绑定窗口、不改尺寸、不注入输入，任意游戏阶段可用。
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Callable, Optional

from GameBot.runner.driver.claim_registry import ClaimRegistry
from GameBot.runner.driver.process_lock import NamedMutex
from GameBot.utils import ClaimError, StopTaskError, logger

_user32 = ctypes.windll.user32
_user32.IsWindow.argtypes = [wintypes.HWND]
_user32.IsWindow.restype = wintypes.BOOL
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.IsIconic.restype = wintypes.BOOL


def _window_usable(hwnd: int) -> bool:
    """窗口存活且未最小化（最小化窗口客户区 0x0、WGC 无法取帧，认领了也跑不了）。"""
    return bool(_user32.IsWindow(int(hwnd))) and not _user32.IsIconic(int(hwnd))


def player_matches(owner: str, target: str) -> bool:
    """归属名匹配：OCR 归属名可能带后缀/空格噪音，归一化后包含匹配。"""
    if not owner or not target:
        return False
    o = "".join(str(owner).split()).casefold()
    t = "".join(str(target).split()).casefold()
    return o == t or o.startswith(t) or t in o


def get_registry(business, cfg: dict) -> ClaimRegistry:
    """取业务对象持有的共享注册表（惰性创建，配置项见 base.toml [this.claim_registry]）。"""
    reg = getattr(business, "_claim_registry_obj", None)
    if reg is None:
        reg_cfg = cfg.get("claim_registry", {}) if isinstance(cfg, dict) else {}
        reg = ClaimRegistry(
            path=reg_cfg.get("path") or None,
            lock_timeout_ms=int(reg_cfg.get("lock_timeout_ms", 5000)),
        )
        business._claim_registry_obj = reg
    return reg


def ensure_registered(business, cfg: dict, player: str = "", task: str = "") -> ClaimRegistry:
    """首次参与认领流程时把本实例登记进注册表（懒注册，幂等）。"""
    reg = get_registry(business, cfg)
    if not getattr(business, "_instance_registered", False):
        reg.register_instance(
            player or getattr(business, "target_player", ""),
            task or getattr(business, "task_name", ""),
        )
        business._instance_registered = True
    return reg


def self_kk_pid(business, cfg: dict, target_player: str = "", reg: Optional[ClaimRegistry] = None) -> int:
    """本账号 KK 进程 PID：已识别缓存 → 注册表 player→kk_pid 查询；未知返回 0。

    注册表命中时写回 ``business._kk_pid`` 缓存，后续认领/弹窗过滤直接复用。
    """
    pid = getattr(business, "_kk_pid", 0)
    if pid:
        return pid
    player = target_player or getattr(business, "target_player", "")
    if player:
        reg = reg or get_registry(business, cfg)
        pid = reg.kk_pid_of(player)
        if pid:
            business._kk_pid = pid
            logger.info(f"注册表命中 kk_pid: {player} → {pid}，跳过识别直接采用")
    return pid


def claim_window(
    *,
    kind: str,
    candidates_fn: Callable[[], list],
    mutex_prefix: str,
    resolve_owner: Callable[[int], Optional[bool]],
    identify: Optional[Callable[[int], bool]] = None,
    timeout: float = 60.0,
    retry_interval: float = 0.5,
    stop_event=None,
    cached_hwnd: int = 0,
    registry: Optional[ClaimRegistry] = None,
) -> tuple[int, NamedMutex]:
    """认领一个归属本脚本的窗口，返回 (hwnd, 持有的窗口互斥锁)。

    :param kind: 窗口类型（war3/kk_room/kk_hall 等），用于锁名与注册表 key
    :param candidates_fn: 候选窗口枚举回调，返回 hwnd 列表
    :param mutex_prefix: per-hwnd 命名互斥锁前缀（如 ``Local\\GameBot_War3_``）
    :param resolve_owner: 归属判定 hwnd -> True（本账号）/False（他人）/None（未知，
        转 identify）；实现应为只读查表，不对窗口做任何操作
    :param identify: 可选自举回调 hwnd -> bool（识别为本账号返回 True）。
        仅启动场景识别路径传入；回调内部自行完成绑定/OCR 并写注册表
    :param timeout: 认领总超时（秒）
    :param retry_interval: 每轮扫描间隔（秒）
    :param stop_event: 停止事件，置位时抛 StopTaskError
    :param cached_hwnd: 本进程已认领的缓存句柄，存活且复核一致时直接复用
    :param registry: 共享注册表（测试可注入），默认机器级实例
    :return: (认领成功的 hwnd, 持有的 NamedMutex)；锁由调用方持有至显式释放
    :raises ClaimError: 超时未认领到归属窗口（候选数/占用情况写入消息）
    :raises StopTaskError: 收到停止信号
    """
    reg = registry or ClaimRegistry()

    def _wait(sec: float) -> None:
        if stop_event is not None:
            if stop_event.wait(sec):
                raise StopTaskError("用户请求停止任务")
        else:
            time.sleep(sec)

    # 缓存复用：hwnd 存活且归属复核一致 → 重新持锁直接返回
    if cached_hwnd and _window_usable(cached_hwnd) and resolve_owner(cached_hwnd) is True:
        mutex = NamedMutex(f"{mutex_prefix}{cached_hwnd}")
        if mutex.try_acquire():
            reg.record_window(kind, cached_hwnd)
            logger.info(f"复用已认领 {kind} 窗口 hwnd={cached_hwnd}")
            return cached_hwnd, mutex
        mutex.release()

    start = time.time()
    last_candidates = 0
    last_occupied = 0
    while True:
        candidates = [h for h in candidates_fn() or [] if _window_usable(h)]
        last_candidates = len(candidates)
        # 单开快速路径：本机仅本脚本存活且候选唯一 → 跳过归属判定直接认领
        fast_path = reg.alive_count() <= 1 and len(candidates) == 1
        occupied = 0
        for hwnd in candidates:
            if stop_event is not None and stop_event.is_set():
                raise StopTaskError("用户请求停止任务")
            mutex = NamedMutex(f"{mutex_prefix}{hwnd}")
            if not mutex.try_acquire():
                occupied += 1
                logger.info(f"{kind} 窗口 {hwnd} 已被其他脚本认领，跳过")
                continue
            matched = False
            try:
                if fast_path:
                    matched = True
                else:
                    resolved = resolve_owner(hwnd)
                    if resolved is None and identify is not None:
                        resolved = bool(identify(hwnd))
                    matched = bool(resolved)
            finally:
                if not matched:
                    mutex.release()
            if matched:
                kk_pid = reg.record_window(kind, hwnd)
                logger.info(f"已认领 {kind} 窗口 hwnd={hwnd}" + (f"，kk_pid={kk_pid}" if kk_pid else ""))
                return hwnd, mutex
        last_occupied = occupied
        if time.time() - start >= timeout:
            break
        _wait(retry_interval)
    raise ClaimError(
        f"认领 {kind} 窗口超时（{timeout}s）：共 {last_candidates} 个候选，"
        f"{last_occupied} 个已被占用，归属判定均未命中"
    )
