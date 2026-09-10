"""圣骑士风龙后台绑定参数手动测试。

从内置的有效组合中选一组跑，手动按 Ctrl+C 停止。

用法：
    uv run python tests/manual/test_paladin_wind_dragon_bind.py --case 1
    uv run python tests/manual/test_paladin_wind_dragon_bind.py --case 4 --duration 30
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

# 本环境（管理员 + dx2 + mode 4）实测有效的组合。
# 用 --case N 选择，编号从 1 开始。
DEFAULT_CASES = [
    {"display": "dx2", "mouse": "windows",                    "keypad": "windows",           "public": "", "mode": 4},
    {"display": "dx2", "mouse": "windows2",                   "keypad": "windows",           "public": "", "mode": 4},
    {"display": "dx2", "mouse": "windows3",                   "keypad": "windows",           "public": "", "mode": 4},
    {"display": "dx2", "mouse": "dx.mouse.position.lock.api", "keypad": "windows",           "public": "", "mode": 4},
    {"display": "dx2", "mouse": "dx.mouse.focus.input.api",  "keypad": "windows",           "public": "", "mode": 4},
    {"display": "dx2", "mouse": "dx.mouse.clip.lock.api",     "keypad": "windows",           "public": "", "mode": 4},
    {"display": "dx2", "mouse": "dx.mouse.state.api",         "keypad": "windows",           "public": "", "mode": 4},
    {"display": "dx2", "mouse": "dx.mouse.api",               "keypad": "windows",           "public": "", "mode": 4},
    {"display": "dx2", "mouse": "dx.mouse.cursor",            "keypad": "windows",           "public": "", "mode": 4},
    {"display": "dx2", "mouse": "windows2",                   "keypad": "dx.keypad.input.lock.api", "public": "", "mode": 4},
    {"display": "dx2", "mouse": "windows2",                   "keypad": "dx.keypad.api",            "public": "", "mode": 4},
    {"display": "dx2", "mouse": "dx.mouse.position.lock.api", "keypad": "windows",          "public": "dx.public.active.api", "mode": 4},
]


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

    logger.info(f"\n测试组合 [{case}]")
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
            task.war3.set_client_size(task.war3.hwnd)
            x1, y1, x2, y2 = dm.get_client_rect(task.war3.hwnd)
            task.client_center = [(x2 - x1) // 2, (y2 - y1) // 2]

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
        "--case",
        type=int,
        default=None,
        help="跑第几组（1~12），不指定则列出所有组合",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0,
        help="运行秒数，0 表示手动停止（默认 0）",
    )
    args = parser.parse_args()

    setup_log_file("风龙后台绑定测试")

    if args.case is None:
        logger.info("内置有效组合：")
        for i, c in enumerate(DEFAULT_CASES, 1):
            logger.info(f"  [{i}] {c}")
        return 0

    if args.case < 1 or args.case > len(DEFAULT_CASES):
        logger.error(f"--case 超出范围，有效范围 1~{len(DEFAULT_CASES)}")
        return 1

    case = copy.deepcopy(DEFAULT_CASES[args.case - 1])
    base_cfg = config.load_task("war3.jiubing2.tasks.others.paladin_wind_dragon")
    base_cfg = copy.deepcopy(base_cfg)

    dm = create_dm_client()
    try:
        result = run_case(base_cfg, dm, case, args.duration)
    finally:
        dm.close()

    report_path = OUT_DIR / "report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info(f"\n报告已保存: {report_path.resolve()}")

    return 0 if result["bind_ok"] and result["total_casts"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
