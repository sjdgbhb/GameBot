"""圣骑士风龙后台绑定参数手动测试。

只跑一组绑定参数，手动在游戏中观察，按 Ctrl+C 停止。

用法：
    uv run python tests/manual/test_paladin_wind_dragon_bind.py
    uv run python tests/manual/test_paladin_wind_dragon_bind.py --mouse windows2
    uv run python tests/manual/test_paladin_wind_dragon_bind.py --mouse "dx.mouse.position.lock.api" --duration 30
    uv run python tests/manual/test_paladin_wind_dragon_bind.py --keypad "dx.keypad.api" --public "dx.public.active.api"

注意事项：
- 需要以管理员权限运行（dx 绑定模式要求）
- 测试前请将圣骑士角色置于可释放技能状态
- 脚本会真实发送按键和点击，请在合适的游戏场景下运行
- 后台绑定下 War3 窗口可被遮挡，但不能最小化
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import threading
import time
from pathlib import Path

from GameBot.config import config
from GameBot.runner.driver import create_dm_client
from GameBot.runner.tasks.war3.jiubing2.others.paladin_wind_dragon import PaladinWindDragonTask
from GameBot.utils import DmError, StopTaskError, logger, setup_log_file

OUT_DIR = Path("logs/diag_wind_dragon_bind")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 默认用本环境实测最稳的一组：管理员 + dx2 + mode 4
# 可覆盖：--display / --mouse / --keypad / --public / --mode / --duration
DEFAULT_DISPLAY = "dx2"
DEFAULT_MOUSE = "dx.mouse.position.lock.api"
DEFAULT_KEYPAD = "windows"
DEFAULT_PUBLIC = ""
DEFAULT_MODE = 4

# 其它在本环境也有效的组合，需要时可通过 --mouse/--keypad 传入：
#   mouse: windows, windows2, windows3,
#          dx.mouse.focus.input.api, dx.mouse.clip.lock.api,
#          dx.mouse.state.api, dx.mouse.api
#   keypad: dx.keypad.input.lock.api, dx.keypad.api
#   public: dx.public.active.api


def _build_case(args: argparse.Namespace) -> dict:
    """把 CLI 参数合并成一组绑定参数。"""
    return {
        "display": args.display or DEFAULT_DISPLAY,
        "mouse": args.mouse or DEFAULT_MOUSE,
        "keypad": args.keypad or DEFAULT_KEYPAD,
        "public": args.public if args.public is not None else DEFAULT_PUBLIC,
        "mode": int(args.mode) if args.mode is not None else DEFAULT_MODE,
    }


def run_case(base_cfg: dict, dm, case: dict, duration: float) -> dict:
    """运行一组绑定参数，duration <= 0 时一直跑到手动停止。"""
    public = case.get("public", "")
    label = (
        f"wd_{case['display']}_{case['mouse']}_{case['keypad']}"
        f"{('_' + public.replace('|', '_')) if public else ''}_mode{case['mode']}"
    )

    result = {
        "label": label,
        "case": case,
        "duration": duration,
        "actual_duration": 0.0,
        "bind_ok": False,
        "detect_ok": False,
        "ready_states": {},
        "casts": {},
        "total_casts": 0,
        "error": "",
    }

    logger.info(f"\n测试组合: {case}")
    if duration > 0:
        logger.info(f"运行 {duration}s 后自动停止")
    else:
        logger.info("按 Ctrl+C 手动停止")

    cfg = copy.deepcopy(base_cfg)
    task_path = cfg["war3"]["jiubing2"]["tasks"]["others"]["paladin_wind_dragon"]
    task_path["bind_mode"] = "background"
    cfg["war3"]["bind_multi"] = {
        "display": case["display"],
        "mouse": case["mouse"],
        "keypad": case["keypad"],
        "public": public,
        "mode": case["mode"],
        "bind_delay": 1.5,
    }

    task = PaladinWindDragonTask(cfg, dm=dm)

    try:
        with dm.bind_window(
            task.war3.hwnd, bind_cfg=cfg["war3"]["bind_multi"]
        ):
            # 注入测试用例的绑定配置（后台模式会读 war3.bind_multi）
            task.war3.set_client_size(task.war3.hwnd)
            x1, y1, x2, y2 = dm.get_client_rect(task.war3.hwnd)
            task.client_center = [(x2 - x1) // 2, (y2 - y1) // 2]

            # 先检测一次技能图标
            ready_states = {}
            detect_ok = False
            for skill in task.skills:
                key = skill["key"]
                ready = task._is_ready(skill)
                ready_states[key] = ready
                if ready:
                    detect_ok = True
                    logger.info(f"  技能 {key.upper()} 检测: 就绪")
                else:
                    logger.info(f"  技能 {key.upper()} 检测: 未就绪/冷却中")
            result["ready_states"] = ready_states
            result["detect_ok"] = detect_ok

            # 启动挂机循环
            stop_event = threading.Event()
            timer = None
            if duration > 0:
                timer = threading.Timer(duration, stop_event.set)
                timer.daemon = True
                timer.start()

            task._stop_event = stop_event
            start_time = time.monotonic()
            try:
                task.run_core(task.war3.hwnd)
            except StopTaskError:
                logger.info("  到达测试时长，停止循环")
            except KeyboardInterrupt:
                logger.info("  用户手动停止")
            finally:
                if timer is not None:
                    timer.cancel()
            result["actual_duration"] = round(time.monotonic() - start_time, 2)

        result["bind_ok"] = True

    except DmError as e:
        result["error"] = str(e)
        logger.error(f"  {label}: 大漠错误: {e}")

    result["casts"] = {k: v for k, v in task._cast_counts.items()}
    result["total_casts"] = sum(result["casts"].values())
    logger.info(
        f"  [{label}] 测试结束，实际运行 {result['actual_duration']}s，"
        f"bind={result['bind_ok']} detect={result['detect_ok']} "
        f"casts={result['total_casts']} ({result['casts']})"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="圣骑士风龙后台绑定参数手动测试")
    parser.add_argument(
        "--display",
        type=str,
        default=None,
        help=f"截图模式（默认 {DEFAULT_DISPLAY}）",
    )
    parser.add_argument(
        "--mouse",
        type=str,
        default=None,
        help=f"鼠标仿真模式（默认 {DEFAULT_MOUSE}）",
    )
    parser.add_argument(
        "--keypad",
        type=str,
        default=None,
        help=f"键盘仿真模式（默认 {DEFAULT_KEYPAD}）",
    )
    parser.add_argument(
        "--public",
        type=str,
        default=None,
        help=f'公共属性（默认 "{DEFAULT_PUBLIC}"）',
    )
    parser.add_argument(
        "--mode",
        type=int,
        default=None,
        help=f"绑定 mode（默认 {DEFAULT_MODE}）",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0,
        help="运行秒数，0 表示手动停止（默认 0）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="JSON 报告输出路径",
    )
    args = parser.parse_args()

    setup_log_file("风龙后台绑定测试")

    base_cfg = config.load_task("war3.jiubing2.tasks.others.paladin_wind_dragon")
    base_cfg = copy.deepcopy(base_cfg)

    case = _build_case(args)
    dm = create_dm_client()
    try:
        result = run_case(base_cfg, dm, case, args.duration)
    finally:
        dm.close()

    report_path = Path(args.output) if args.output else OUT_DIR / "report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info(f"\n报告已保存: {report_path.resolve()}")

    return 0 if result["bind_ok"] and result["total_casts"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
