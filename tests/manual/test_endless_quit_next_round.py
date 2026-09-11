"""War3 退出游戏 → 延迟 5 秒 → KK 开下一局 实测脚本。

前置条件：
- War3 已在游戏中（任意 RPG 地图、任意时刻均可）
- KK 平台已登录

流程：
1. 找到 War3 窗口并绑定
2. quit_game 退出当前局
3. 等待 5 秒
4. KK 开第二局（找房/建房/启动游戏）
5. wait_for_game_window 等待 War3 窗口出现
6. 确认第二局已启动

运行：uv run python tests/manual/test_endless_quit_next_round.py
"""

import time

from GameBot.config import config
from GameBot.runner.business.kk import KKBusiness
from GameBot.runner.business.war3 import War3Business
from GameBot.runner.driver import create_dm_client
from GameBot.utils import logger, setup_log_file

# 退出后等待多少秒再开下一局
LOOP_INTERVAL = 5


def main():
    setup_log_file("退出再开测试")
    logger.info("############################# War3 退出再开测试 #############################")

    cfg = config.load_task("war3.jiubing2.tasks.endless.endless")
    war3_cfg = cfg.get("war3", {})
    kk_cfg = cfg.get("kk", {})

    dm = create_dm_client()
    war3 = War3Business(dm, war3_cfg)
    kk = KKBusiness(dm, kk_cfg)

    # ── 第 1 步：找到当前 War3 窗口 ──
    logger.info("请确保 War3 已在游戏中，5 秒后开始查找窗口...")
    time.sleep(5)

    hwnd = dm.get_active_window(war3_cfg["window_class"], war3_cfg["window_title"])
    if not hwnd:
        logger.error("未找到 War3 窗口，请确保游戏正在运行")
        return

    logger.info(f"找到 War3 窗口 hwnd={hwnd}")

    # ── 第 2 步：退出当前局 ──
    logger.info("=== 第 1 局：退出游戏 ===")
    war3.set_client_size(hwnd)
    with dm.bind_window(hwnd, bind_cfg=war3_cfg.get("bind", {})):
        war3.quit_game()
    logger.info("第 1 局已退出")

    # ── 第 3 步：延迟 ──
    logger.info(f"=== 等待 {LOOP_INTERVAL} 秒后开始第二局 ===")
    time.sleep(LOOP_INTERVAL)

    # ── 第 4 步：KK 开第二局 ──
    logger.info("=== 第 2 局：KK 阶段 ===")
    room_hwnd = kk.dismiss_room_popups(dm)
    if room_hwnd:
        logger.info("找到已有房间，直接开始游戏")
        kk.start_game(dm, room_hwnd=room_hwnd)
    else:
        logger.info("未找到 KK 房间，开始自动创建房间")
        kk.dismiss_hall_popups(dm)
        map_name = cfg.get("game", {}).get("map_name", "九种兵器2诸神战场")
        room_hwnd = kk.create_room(dm, map_name=map_name)
        if not room_hwnd:
            logger.error("创建房间失败，测试终止")
            return
        kk.start_game(dm, room_hwnd=room_hwnd)

    # ── 第 5 步：等待 War3 窗口出现 ──
    logger.info("=== 第 2 局：等待 War3 窗口 ===")
    hwnd2 = war3.wait_for_game_window(timeout=60)
    if hwnd2:
        logger.info(f"第 2 局 War3 窗口已出现 hwnd={hwnd2}，测试通过")
    else:
        logger.error("等待第 2 局 War3 窗口超时，测试失败")
        return

    logger.info("############################# 测试结束 #############################")


if __name__ == "__main__":
    main()
