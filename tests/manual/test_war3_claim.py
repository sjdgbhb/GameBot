"""War3 多开认领冒烟测试 — 聊天 token 归属识别实机验证。

用法：
    python tests/manual/test_war3_claim.py                # 枚举窗口 + 认领第一个空闲窗口
    python tests/manual/test_war3_claim.py --player 玩家A # 按玩家名认领
    python tests/manual/test_war3_claim.py --hold 60      # 认领后持锁 60s（供第二脚本验证占用）

验证点：
    1. find_windows 枚举出全部 war3 窗口
    2. 互斥锁按 hwnd 认领/跳过
    3. send_msg 发 token 后 OCR 聊天区能读回并解析出玩家名
    4. --hold 期间另开一脚本执行，应跳过本窗口
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from GameBot.config import config
from GameBot.runner import create_dm_client
from GameBot.runner.business.war3 import War3Business
from GameBot.utils import logger, setup_log_file


def main():
    parser = argparse.ArgumentParser(description="War3 多开认领冒烟测试")
    parser.add_argument("--player", default="", help="目标玩家名（为空则认领第一个空闲窗口）")
    parser.add_argument("--hold", type=float, default=0, help="认领后持锁秒数（默认 0=立即退出）")
    args = parser.parse_args()

    setup_log_file("war3认领冒烟")
    cfg = config.load_task("war3")
    war3_cfg = cfg.get("war3", {})
    dm = create_dm_client()
    war3 = War3Business(dm, war3_cfg)
    war3.target_player = args.player

    wins = dm.find_windows(war3_cfg.get("window_class", ""), war3_cfg.get("window_title", ""))
    logger.info(f"枚举到 {len(wins)} 个 war3 窗口: {[w['hwnd'] for w in wins]}")

    hwnd = war3.claim_war3_window(target_player=args.player)
    if not hwnd:
        logger.error("认领失败：无可用窗口")
        sys.exit(1)
    logger.info(f"认领成功: hwnd={hwnd}, 归属玩家={war3.claimed_owner or '未识别'}")

    if args.hold > 0:
        logger.info(f"持锁 {args.hold}s，期间可用第二个脚本验证占用")
        time.sleep(args.hold)
        logger.info("持锁结束，退出（互斥锁随进程释放）")


if __name__ == "__main__":
    main()
