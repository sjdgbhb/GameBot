"""多开窗口认领实机场景测试（openspec refactor-window-claim 场景验证）。

拉起真实任务子进程 → 监听认领日志 → 校验注册表归属 → 终止进程，
只验证窗口认领链路，不跑完整业务。

场景 1（multi）多局任务 —— 认 KK 房间 → 每局认 war3，局数=2 跑两轮
    验证"认领 → 局间释放 → 重新认领"完整链路：
    - 善木木 endless（多局无尽）
    - 岁月神偷 endless（多局无尽）
    - 火焰头槌 game_count（刷局数）
    脚本为每个实例生成临时认领测试变体（继承玩家变体，games=2、
    局内时长压缩），测试结束删除，不污染正式变体配置。
    前置：三个账号各自已创建好密码房。

场景 2（ingame）局内任务 —— 游戏内启动，认领成功即终止（不做游戏操作）：
    - 善木木 paladin_wind_dragon（圣骑风龙）+ 岁月神偷 fishing（钓鱼）：两人同一局
    - 火焰头槌 fishing（钓鱼）：另一局
    前置：组队两账号在同一房间已进入同一局游戏，火焰头槌在另一局；
    三个账号 war3 窗口均已存在。

用法：
    uv run python tests/manual/test_claim_scenarios.py                # 两场依次跑
    uv run python tests/manual/test_claim_scenarios.py multi          # 只跑场景1
    uv run python tests/manual/test_claim_scenarios.py ingame         # 只跑场景2
    uv run python tests/manual/test_claim_scenarios.py multi --clean  # 先清注册表再跑（强制走 token/OCR 自举）
"""

import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from GameBot.runner.driver.claim_registry import (
    ClaimRegistry,
    default_registry_path,
    is_window,
    parent_pid,
    window_pid,
)
from GameBot.utils import logger, setup_log_file

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TASKS_DIR = PROJECT_ROOT / "src/GameBot/config/data/war3/jiubing2/tasks"

# 认领成功日志标记：只认 claim_window 的"kk_pid="行（window_manager 的
# "归属玩家"行是同一事件的重复日志，不计数）
_RE_ROOM_CLAIM = re.compile(r"已认领 kk_room 窗口 hwnd=(\d+)，kk_pid=(\d+)")
_RE_WAR3_CLAIM = re.compile(r"已认领 war3 窗口 hwnd=(\d+)，kk_pid=(\d+)")
# 失败标记
_RE_FAIL = re.compile(r"ClaimError|认领超时|拒绝重复启动|未捕获异常")

# 任务级 error sink 也会把 ERROR 打到控制台；以下文本视为场景失败
_FAIL_TEXTS = ("认领超时", "拒绝重复启动", "未捕获异常", "ClaimError")


@dataclass
class Instance:
    """一个待验证的任务实例。"""

    player: str          # 预期归属玩家（变体 target_player）
    module: str          # 任务模块，如 GameBot.runner.tasks...endless.endless
    variant: str         # 启动变体名（TOML 叶子名）
    war3_claims: int     # 期望的 war3 认领次数（game_count=2 验证重认领，其余=1）
    expect_room: bool    # 是否期待 kk_room 认领（多局任务从房间启动）
    wait_marker: str = ""       # 额外完成标记：日志出现该文本才算达标（如"已进入游戏"）
    marker_dwell: float = 0     # 标记出现后停留秒数再终止（war3 只能在游戏内退出）
    temp_variant: Path = None   # 临时变体文件（场景1 生成）
    proc: subprocess.Popen = None
    room_claims: list = field(default_factory=list)   # 认领到的 kk_room hwnd
    war3_claim_hwnds: list = field(default_factory=list)  # 认领到的 war3 hwnd
    marker_at: float = 0        # wait_marker 命中时间戳
    failed: str = ""     # 命中的失败文本
    out_lines: list = field(default_factory=list)     # 输出尾部缓冲（失败时打印）
    done: threading.Event = field(default_factory=threading.Event)


# ── 场景定义 ────────────────────────────────────────────────

def _multi_instances() -> list:
    """场景1：三个多局任务，games=2。"""
    return [
        Instance(
            player="善木木",
            module="GameBot.runner.tasks.war3.jiubing2.endless.endless",
            variant="endless_claimtest_善木木",
            war3_claims=1,
            expect_room=True,
            wait_marker="已进入游戏",
            marker_dwell=15,
            temp_variant=TASKS_DIR / "endless" / "endless_claimtest_善木木.toml",
        ),
        Instance(
            player="岁月神偷",
            module="GameBot.runner.tasks.war3.jiubing2.endless.endless",
            variant="endless_claimtest_岁月神偷",
            war3_claims=1,
            expect_room=True,
            wait_marker="已进入游戏",
            marker_dwell=15,
            temp_variant=TASKS_DIR / "endless" / "endless_claimtest_岁月神偷.toml",
        ),
        Instance(
            player="火焰头槌",
            module="GameBot.runner.tasks.war3.jiubing2.others.game_count",
            variant="game_count_claimtest_火焰头槌",
            war3_claims=2,
            expect_room=True,
            temp_variant=TASKS_DIR / "others" / "game_count_claimtest_火焰头槌.toml",
        ),
    ]


_MULTI_OVERRIDE = {
    "endless": "games = 2\nmin_level = 15\nmax_level = 15\nwait_time = 5\nloop_interval_time = 3\n",
    "game_count": "games = 2\nidle_time = 15\nloop_interval_time = 3\n",
}

_MULTI_BASE = {
    "善木木": ("endless", "endless_善木木", "endless.endless"),
    "岁月神偷": ("endless", "endless_岁月神偷", "endless.endless"),
    "火焰头槌": ("others", "game_count_火焰头槌", "others.game_count"),
}


def _write_temp_variant(inst: Instance):
    """生成临时认领测试变体：继承玩家变体（带入 target_player），压缩局数/局内时长。"""
    group, base_variant, _ = _MULTI_BASE[inst.player]
    base_full = f"war3.jiubing2.tasks.{group}.{base_variant}"
    override_key = "endless" if "endless" in base_variant else "game_count"
    inst.temp_variant.write_text(
        f'extends = ["{base_full}"]\n\n'
        "[this]\n"
        f'name = "认领测试-{inst.player}"\n'
        + _MULTI_OVERRIDE[override_key],
        encoding="utf-8",
    )


def _ingame_instances() -> list:
    """场景2：组队同局（善木木风龙 + 岁月神偷钓鱼）+ 火焰头槌另一局钓鱼。"""
    return [
        Instance(
            player="善木木",
            module="GameBot.runner.tasks.war3.jiubing2.wind_dragon.paladin_wind_dragon",
            variant="paladin_wind_dragon_善木木",
            war3_claims=1,
            expect_room=False,
        ),
        Instance(
            player="岁月神偷",
            module="GameBot.runner.tasks.war3.jiubing2.others.fishing",
            variant="fishing_岁月神偷",
            war3_claims=1,
            expect_room=False,
        ),
        Instance(
            player="火焰头槌",
            module="GameBot.runner.tasks.war3.jiubing2.others.fishing",
            variant="fishing_火焰头槌",
            war3_claims=1,
            expect_room=False,
        ),
    ]


# ── 子进程监控 ──────────────────────────────────────────────

def _drain(inst: Instance):
    """读子进程输出，累积认领/失败标记。"""
    for line in inst.proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        inst.out_lines.append(line)
        if len(inst.out_lines) > 60:
            inst.out_lines.pop(0)
        print(f"  [{inst.player}] {line}", flush=True)
        if m := _RE_ROOM_CLAIM.search(line):
            hwnd = int(m.group(1))
            if hwnd not in inst.room_claims:
                inst.room_claims.append(hwnd)
        if m := _RE_WAR3_CLAIM.search(line):
            hwnd = int(m.group(1))
            if hwnd not in inst.war3_claim_hwnds:
                inst.war3_claim_hwnds.append(hwnd)
        if any(t in line for t in _FAIL_TEXTS):
            inst.failed = line
        if inst.wait_marker and inst.wait_marker in line and not inst.marker_at:
            inst.marker_at = time.time()
    if inst.war3_claim_hwnds or inst.room_claims:
        return
    inst.failed = inst.failed or "进程退出且未发生任何认领"


def _launch(instances: list):
    for inst in instances:
        logger.info(f"启动实例: {inst.player} → {inst.module} {inst.variant}")
        inst.proc = subprocess.Popen(
            [sys.executable, "-u", "-m", inst.module, inst.variant],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        threading.Thread(target=_drain, args=(inst,), daemon=True).start()
        time.sleep(0.5)  # 错开 dm_bridge 启动


def _wait_claims(instances: list, timeout: float) -> bool:
    """等待所有实例完成认领或任一失败/超时。

    达标条件 = war3 认领次数满足 +（如需）房间认领 +（如需）标记命中且停留期满。
    达标即杀进程——只验证认领链路，不做后续游戏操作。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if any(i.failed for i in instances):
            return False
        if all(i.done.is_set() or i.failed for i in instances):
            return True
        now = time.time()
        for i in instances:
            if i.done.is_set() or i.failed:
                continue
            claims_ok = len(i.war3_claim_hwnds) >= i.war3_claims and (
                not i.expect_room or i.room_claims
            )
            dwell_ok = not i.wait_marker or (
                i.marker_at and now - i.marker_at >= i.marker_dwell
            )
            if claims_ok and dwell_ok:
                i.done.set()
                if i.proc.poll() is None:
                    try:
                        i.proc.kill()
                    except OSError:
                        pass
            elif i.proc.poll() is not None:
                i.failed = f"进程提前退出 rc={i.proc.returncode}"
        time.sleep(0.3)
    return False


def _kill_all(instances: list):
    for inst in instances:
        if inst.proc and inst.proc.poll() is None:
            try:
                inst.proc.kill()
            except OSError:
                pass


# ── 注册表校验 ──────────────────────────────────────────────

def _verify(instances: list) -> bool:
    """校验注册表归属记录：kk_owner 映射、窗口记录与真实进程关系一致。"""
    reg = ClaimRegistry(default_registry_path())
    ok = True
    for inst in instances:
        kk_pid = reg.kk_pid_of(inst.player)
        if not kk_pid:
            logger.error(f"[{inst.player}] 注册表无 kk_owner 记录")
            ok = False
            continue
        for hwnd in inst.room_claims:
            real = window_pid(hwnd)
            stored = reg.window_kk_pid("kk_room", hwnd)
            if real != kk_pid or stored != kk_pid:
                logger.error(
                    f"[{inst.player}] kk_room hwnd={hwnd} 归属不符: "
                    f"window_pid={real}, 注册表={stored}, 期望 kk_pid={kk_pid}"
                )
                ok = False
            else:
                logger.info(f"[{inst.player}] kk_room hwnd={hwnd} 归属校验通过 kk_pid={kk_pid}")
        for hwnd in inst.war3_claim_hwnds:
            real_pid = window_pid(hwnd)
            if not real_pid or not is_window(hwnd):
                # 旧局窗口随 quit_game 销毁——正常路径，只要求注册表记录已清
                if reg.window_kk_pid("war3", hwnd):
                    logger.error(f"[{inst.player}] war3 hwnd={hwnd} 已销毁但注册表记录残留")
                    ok = False
                else:
                    logger.info(f"[{inst.player}] war3 hwnd={hwnd} 已销毁且记录已清（局间释放）")
                continue
            real = parent_pid(real_pid)
            stored = reg.window_kk_pid("war3", hwnd)
            if real != kk_pid or stored != kk_pid:
                logger.error(
                    f"[{inst.player}] war3 hwnd={hwnd} 归属不符: "
                    f"ppid={real}, 注册表={stored}, 期望 kk_pid={kk_pid}"
                )
                ok = False
            else:
                logger.info(f"[{inst.player}] war3 hwnd={hwnd} 归属校验通过 ppid={kk_pid}")
        # 多局重认领：两轮 hwnd 应不同（新窗口），且注册表只保留最新记录
        if inst.war3_claims >= 2 and len(inst.war3_claim_hwnds) >= 2:
            old, new = inst.war3_claim_hwnds[0], inst.war3_claim_hwnds[-1]
            if old == new:
                logger.error(f"[{inst.player}] 两轮认领同一 hwnd={old}，未发生窗口重建")
                ok = False
            elif reg.window_kk_pid("war3", old):
                logger.error(f"[{inst.player}] 旧 war3 hwnd={old} 记录未释放")
                ok = False
            else:
                logger.info(f"[{inst.player}] 局间释放+重认领验证通过: {old} → {new}")
    return ok


# ── 场景执行 ────────────────────────────────────────────────

def _run_scenario(name: str, instances: list, timeout: float) -> bool:
    """launch → 等认领达标（达标即杀进程）→ 校验注册表归属 → 收尾。"""
    logger.info(f"########## 场景 {name} 开始 ##########")
    _launch(instances)
    ok = _wait_claims(instances, timeout)
    if not ok:
        for inst in instances:
            if inst.failed:
                logger.error(f"[{inst.player}] 失败: {inst.failed}")
                for line in inst.out_lines[-15:]:
                    logger.error(f"    | {line}")
    verified = ok and _verify(instances)
    # 兜底清理（done 时已杀的进程此处幂等）
    _kill_all(instances)
    for inst in instances:
        try:
            inst.proc.wait(timeout=15)
        except Exception:
            pass
    passed = ok and verified
    logger.info(f"########## 场景 {name} {'通过' if passed else '失败'} ##########")
    return passed


def _clean_registry():
    """删除共享注册表，强制所有实例走完整自举（token/OCR）路径。"""
    path = Path(default_registry_path())
    if path.exists():
        path.unlink()
        logger.info(f"已清理注册表: {path}")
    else:
        logger.info(f"注册表不存在（本来干净）: {path}")


def main():
    setup_log_file("认领场景测试")
    args = [a for a in sys.argv[1:] if a != "--clean"]
    which = args[0] if args else "all"
    if "--clean" in sys.argv:
        _clean_registry()
    results = {}

    if which in ("all", "multi"):
        insts = _multi_instances()
        try:
            for inst in insts:
                _write_temp_variant(inst)
            results["multi"] = _run_scenario("multi 多局任务", insts, timeout=600)
        finally:
            for inst in insts:
                if inst.temp_variant and inst.temp_variant.exists():
                    inst.temp_variant.unlink()

    if which in ("all", "ingame"):
        insts = _ingame_instances()
        # 局内任务认领成功即终止，不做游戏操作
        results["ingame"] = _run_scenario("ingame 局内任务", insts, timeout=120)

    logger.info("########## 汇总 ##########")
    for name, ok in results.items():
        logger.info(f"  {name}: {'通过' if ok else '失败'}")
    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
