r"""War3 多开认领冒烟测试 — 后台认领实机验证。

用法（须在主环境 .venv 下运行，即 uv run）：
    uv run python tests\manual\test_war3_claim.py --player 善木木                         # 局内聊天 token 认领
    uv run python tests\manual\test_war3_claim.py --player 善木木 --identify loading      # 加载页只读 OCR 认领（手动开局）
    uv run python tests\manual\test_war3_claim.py --player 善木木 --identify loading --start  # 脚本先认领房间点开始/准备，再认领 war3
    uv run python tests\manual\test_war3_claim.py --hold 300                            # 认领后持锁（供第二脚本验证占用）

验证点：
    1. find_windows 枚举出全部 war3 窗口，互斥锁按 hwnd 认领/跳过
    2. loading：读图期对窗口零操作，OCR 玩家列表定归属
    3. chat（默认）：向聊天框发 gb<pid><hex> token，OCR 聊天区"玩家名：token"定归属
    4. --start：先 claim_room_window 认领 KK 房间并点击开始/准备按钮（同一位置，
       房主=开始游戏、队员=准备），再进入 war3 认领循环等待窗口出现
    5. --hold 期间另开一脚本执行，应跳过本窗口

注意：后台绑定（dx2）需管理员权限；chat 模式会真实发聊天消息；
多开场景请先跑队员脚本（点准备），再跑房主脚本（点开始游戏）。
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
    parser.add_argument("--timeout", type=float, default=None, help="认领总超时秒数（默认读配置 claim_timeout=60）")
    parser.add_argument("--identify", default="chat", choices=["chat", "loading"], help="归属识别方式（默认 chat）")
    parser.add_argument("--start", action="store_true", help="先认领 KK 房间并点击开始/准备按钮")
    args = parser.parse_args()

    setup_log_file("war3认领冒烟")
    dm = create_dm_client()

    if args.start:
        from GameBot.runner.business.kk import KKBusiness

        kk_cfg = config.load_task("kk").get("kk", {})
        kk_cfg["bind_mode"] = "background"
        kk = KKBusiness(dm, kk_cfg)
        room_hwnd, owner_pid = kk.claim_room_window(dm, args.player, claim_timeout=args.timeout)
        if not room_hwnd:
            logger.error("未认领到 KK 房间窗口")
            sys.exit(1)
        # 同一按钮位置：房主=开始游戏，队员=准备
        kk.start_game(dm, room_hwnd=room_hwnd)
        logger.info("已点击开始/准备按钮，等待 war3 窗口出现")

    cfg = config.load_task("war3")
    war3_cfg = cfg.get("war3", {})
    war3_cfg["bind_mode"] = "background"
    war3 = War3Business(dm, war3_cfg)
    war3.target_player = args.player

    wins = dm.find_windows(war3_cfg.get("window_class", ""), war3_cfg.get("window_title", ""))
    logger.info(f"枚举到 {len(wins)} 个 war3 窗口: {[w['hwnd'] for w in wins]}")

    identify = war3.identify_war3_owner if args.identify == "loading" else None
    hwnd = war3.claim_war3_window(target_player=args.player, claim_timeout=args.timeout, identify=identify)
    if not hwnd:
        logger.error("认领失败：无可用窗口")
        sys.exit(1)

    if args.hold > 0:
        logger.info(f"持锁 {args.hold}s，期间可用第二个脚本验证占用")
        time.sleep(args.hold)


if __name__ == "__main__":
    main()
