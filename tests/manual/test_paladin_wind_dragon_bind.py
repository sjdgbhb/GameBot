"""圣骑士风龙后台绑定参数手动测试。

复用钓鱼任务的启停逻辑：浮窗倒计时 + num- 键停止。
从内置有效组合中选一组跑，每组都是实际可施放技能的参数。

用法：
    uv run python tests/manual/test_paladin_wind_dragon_bind.py
    uv run python tests/manual/test_paladin_wind_dragon_bind.py --case 1
    uv run python tests/manual/test_paladin_wind_dragon_bind.py --case 4 --delay 10
"""

from __future__ import annotations

import argparse
import copy
import sys

from GameBot.config import config
from GameBot.runner.tasks.war3.jiubing2.others.paladin_wind_dragon import PaladinWindDragonTask
from GameBot.runner.ui import run_with_float_window
from GameBot.utils import logger, setup_global_exception_hook, setup_log_file

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


def main():
    parser = argparse.ArgumentParser(description="圣骑士风龙后台绑定参数手动测试")
    parser.add_argument(
        "--case",
        type=int,
        default=None,
        help="跑第几组（1~12），不指定则列出所有组合",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=5,
        help="启动前倒计时秒数（默认 5）",
    )
    args = parser.parse_args()

    if args.case is None:
        logger.info("内置有效组合：")
        for i, c in enumerate(DEFAULT_CASES, 1):
            logger.info(f"  [{i}] {c}")
        return 0

    if args.case < 1 or args.case > len(DEFAULT_CASES):
        logger.error(f"--case 超出范围，有效范围 1~{len(DEFAULT_CASES)}")
        return 1

    setup_global_exception_hook()
    setup_log_file("风龙后台绑定测试")

    case = copy.deepcopy(DEFAULT_CASES[args.case - 1])
    cfg = config.load_task("war3.jiubing2.tasks.others.paladin_wind_dragon")

    # 注入后台绑定参数
    task_path = cfg["war3"]["jiubing2"]["tasks"]["others"]["paladin_wind_dragon"]
    task_path["bind_mode"] = "background"
    cfg["war3"]["bind_multi"] = {
        "display": case["display"],
        "mouse": case["mouse"],
        "keypad": case["keypad"],
        "public": case.get("public", ""),
        "mode": case["mode"],
        "bind_delay": 1.5,
    }

    def task_wrapper(stop_event, progress_callback):
        PaladinWindDragonTask(
            cfg,
            stop_event=stop_event,
            progress_callback=progress_callback,
        ).run()

    run_with_float_window(
        "风龙绑定测试",
        task_wrapper,
        countdown_seconds=args.delay,
        float_cfg=cfg.get("float_window"),
    )


if __name__ == "__main__":
    sys.exit(main())
