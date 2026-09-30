r"""KK 房间多开认领冒烟测试 — 房间聊天 token 归属识别实机验证。

用法（须在主环境 .venv 下运行，即 uv run）：
    uv run python tests\manual\test_kk_room_claim.py                     # 枚举房间 + 认领第一个空闲窗口
    uv run python tests\manual\test_kk_room_claim.py --player 善木木     # 按玩家名认领
    uv run python tests\manual\test_kk_room_claim.py --hold 60           # 认领后持锁 60s（供第二脚本验证占用）

验证点：
    1. find_room_windows 枚举同类名窗口并 OCR"房间号"区域确认房间窗口
    2. 互斥锁按 hwnd 认领/跳过（已被认领的窗口直接跳过，不发 token）
    3. 点击聊天输入框发 token 后 OCR 聊天记录区"玩家名：token"解析归属
    4. --hold 期间另开一脚本执行，应跳过本窗口

注意：会向房间聊天真实发送 gb<pid><hex> 测试消息（两客户端同房时双方都可见，
但 marker 含进程 pid，脚本只认自己发的）；绑定默认 background。
前置：账号须已停留在 KK 房间内。
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from GameBot.config import config
from GameBot.runner import create_dm_client
from GameBot.runner.business.kk import KKBusiness
from GameBot.utils import logger, setup_log_file


def main():
    parser = argparse.ArgumentParser(description="KK 房间多开认领冒烟测试")
    parser.add_argument("--player", default="", help="目标玩家名（为空则认领第一个空闲窗口）")
    parser.add_argument("--hold", type=float, default=0, help="认领后持锁秒数（默认 0=立即退出）")
    parser.add_argument("--timeout", type=float, default=None, help="认领总超时秒数（默认读配置 claim_timeout=60）")
    args = parser.parse_args()

    setup_log_file("kk房间认领冒烟")
    cfg = config.load_task("kk")
    kk_cfg = cfg.get("kk", {})
    kk_cfg["bind_mode"] = "background"
    dm = create_dm_client()
    kk = KKBusiness(dm, kk_cfg)

    rooms = kk.find_room_windows(dm)
    logger.info(f"枚举到 {len(rooms)} 个 KK 房间窗口: {rooms}")
    if not rooms:
        logger.error("未发现 KK 房间窗口——请确认账号已进入房间（房间客户区约 1224x904）")
        sys.exit(1)

    room_hwnd, owner_pid = kk.claim_room_window(
        dm,
        target_player=args.player,
        claim_timeout=args.timeout,
    )
    if not room_hwnd:
        logger.error("认领失败：无可用房间窗口")
        sys.exit(1)

    if args.hold > 0:
        logger.info(f"持锁 {args.hold}s，期间可用第二个脚本验证占用")
        time.sleep(args.hold)
        logger.info("持锁结束，退出（互斥锁随进程释放）")


if __name__ == "__main__":
    main()
