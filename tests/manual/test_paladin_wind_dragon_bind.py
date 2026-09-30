"""圣骑士风龙后台绑定参数手动测试。

从内置有效组合中选一组跑，浮窗倒计时后自动开始，按小键盘 num- 停止。

用法：
    uv run python tests/manual/test_paladin_wind_dragon_bind.py
    uv run python tests/manual/test_paladin_wind_dragon_bind.py --case 1
    uv run python tests/manual/test_paladin_wind_dragon_bind.py --case 4
"""

import argparse
import sys

from GameBot.config import config
from GameBot.runner.tasks.war3.jiubing2.others.paladin_wind_dragon import PaladinWindDragonTask
from GameBot.runner.ui import run_with_float_window
from GameBot.utils import logger, setup_global_exception_hook, setup_log_file

# 候选组合（管理员 + dx2 + mode 4）：
#   case 1 为历史实测可用项；case 2/3 用于验证 dx.mouse.input.lock.api（免费，
#   文档未标收费）能否锁住 war3 前台时的 raw input 干扰——测试时请保持 war3 前台
#   并晃动物理鼠标，若游戏光标不跟随、技能点击落点正确，则该组合可免去"切走焦点"的限制。
DEFAULT_CASES = [
    {
        "display": "dx2",
        "mouse": "dx.mouse.position.lock.api",
        "keypad": "windows",
        "public": "dx.public.active.api",
        "mode": 4,
        "bind_delay": 1.5,
    },
    {
        "display": "dx2",
        "mouse": "dx.mouse.position.lock.api|dx.mouse.position.lock.message|dx.mouse.state.message|dx.mouse.input.lock.api",
        "keypad": "windows",
        "public": "",
        "mode": 4,
        "bind_delay": 1.5,
    },
    {
        "display": "dx2",
        "mouse": "dx.mouse.input.lock.api",
        "keypad": "windows",
        "public": "",
        "mode": 4,
        "bind_delay": 1.5,
    },
]


def main():
    parser = argparse.ArgumentParser(description="圣骑士风龙后台绑定参数手动测试")
    parser.add_argument(
        "--case",
        type=int,
        default=None,
        help="跑第几组（1~15），不指定则列出所有组合",
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

    cfg = config.load_task("war3.jiubing2.tasks.others.paladin_wind_dragon")
    cfg["war3"]["bind_background"] = DEFAULT_CASES[args.case - 1]

    def task_wrapper(stop_event, progress_callback):
        PaladinWindDragonTask(
            cfg,
            stop_event=stop_event,
            progress_callback=progress_callback,
        ).run()

    run_with_float_window(
        "风龙绑定测试",
        task_wrapper,
        countdown_seconds=5,
        float_cfg=cfg.get("float_window"),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
