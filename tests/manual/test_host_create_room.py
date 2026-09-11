"""测试房主在 KK 创建房间的完整流程。

流程：
1. 查找 KK 大厅窗口
2. 判断房间是否已存在（OCR 检测房间窗口按钮关键词）
   - 存在 → 报告成功，结束
   - 不存在 → 继续
3. 搜索地图 → 点击搜索结果进入地图详情 → 点击创建房间 → 输入密码 → 点击创建
4. 验证房间窗口是否出现

直接复用生产代码 KKBusiness，与实际运行逻辑一致。

用法：
    uv run python tests/manual/test_host_create_room.py
    uv run python tests/manual/test_host_create_room.py --delay 10
    uv run python tests/manual/test_host_create_room.py --map "九种兵器2诸神战场"
    uv run python tests/manual/test_host_create_room.py --player "玩家ID"  # 多开时认领归属
    uv run python tests/manual/test_host_create_room.py --bind-mode background  # 强制后台绑定（模拟多开）

前提：KK 大厅窗口已打开，停在主界面（能搜索地图的页面）。
配置来源：src/GameBot/config/data/kk.toml
"""

import argparse
import copy
import sys
import time

from GameBot.config import config
from GameBot.runner.business.kk import KKBusiness
from GameBot.runner.driver import create_dm_client
from GameBot.utils import logger, setup_log_file


def main():
    parser = argparse.ArgumentParser(description="房主 KK 创建房间完整流程测试")
    parser.add_argument("--delay", type=int, default=5, help="启动前等待秒数（默认 5）")
    parser.add_argument("--map", type=str, default="九种兵器2诸神战场", help="地图名（默认九种兵器2诸神战场）")
    parser.add_argument("--bind-mode", type=str, default="foreground", choices=["foreground", "background"],
                        help="绑定模式：foreground(前台 bind) / background(后台 bind_multi)，与生产代码 team/base.py 逻辑一致")
    parser.add_argument("--player", type=str, default="",
                        help="目标玩家 ID（多开场景下通过 OCR 认领属于该玩家的大厅窗口，不传则取第一个匹配窗口）")
    args = parser.parse_args()

    setup_log_file("房主创建房间测试")
    logger.info("=" * 60)
    logger.info("房主 KK 创建房间完整流程测试")
    logger.info("=" * 60)

    for i in range(args.delay, 0, -1):
        logger.info(f"{i} 秒后开始...")
        time.sleep(1)

    # 加载配置
    cfg = config.load_task("kk")
    kk_cfg = cfg.get("kk", {})

    # 绑定配置选择逻辑与生产代码（team/base.py）一致：
    # foreground 用 bind（前台），background 用 bind_multi（后台）
    if args.bind_mode == "background":
        if "bind_multi" in kk_cfg:
            kk_cfg = copy.deepcopy(kk_cfg)
            kk_cfg["bind"] = kk_cfg["bind_multi"]
            logger.info(f"bind-mode=background，已切换到后台绑定: {kk_cfg['bind']}")
    else:
        logger.info(f"bind-mode=auto，使用前台绑定: {kk_cfg.get('bind', {})}")

    dm = create_dm_client()
    logger.info(f"大漠版本: {dm.version}")

    # 复用生产代码 KKBusiness
    kk = KKBusiness(dm, kk_cfg)

    try:
        # 1. 查找 KK 大厅窗口（多开时通过 --player 认领归属）
        hall_hwnd = kk._find_hall_hwnd(dm, target_player=args.player)
        if not hall_hwnd:
            logger.error("未找到 KK 大厅窗口")
            return 1
        logger.info(f"大厅窗口: hwnd={hall_hwnd}" + (f"，归属玩家: {args.player}" if args.player else ""))

        main_size = tuple(kk_cfg.get("main", {}).get("window_size", [1332, 945]))
        dm.set_client_size(hall_hwnd, *main_size)
        time.sleep(0.5)
        pid = dm.get_window_process_id(hall_hwnd)
        logger.info(f"大厅进程 PID: {pid}")

        # 2. 清理弹窗（操作 KK 窗口时随时可能弹出，先清掉再判断）
        kk.dismiss_hall_popups(dm, exclude_hwnds={hall_hwnd}, owner_pid=pid)

        # 3. 判断房间是否已存在
        logger.info("检查房间是否已存在...")
        room_hwnd = kk._find_room_window(dm, owner_pid=pid)
        if room_hwnd:
            logger.info(f"房间已存在，房间窗口: hwnd={room_hwnd}，无需创建")
            return 0

        logger.info("房间不存在，开始创建房间流程")

        # 4. 创建房间前再清一次弹窗（上一步操作可能触发新弹窗）
        kk.dismiss_hall_popups(dm, exclude_hwnds={hall_hwnd}, owner_pid=pid)

        # 5. 创建房间（搜索地图 → 点击搜索结果 → 点击创建房间 → 输入密码 → 点击创建）
        room_hwnd = kk.create_room(
            dm,
            map_name=args.map,
            hall_hwnd=hall_hwnd,
            owner_pid=pid,
        )

        # 6. 验证结果
        if room_hwnd:
            logger.info(f"创建房间成功，房间窗口: hwnd={room_hwnd}")
            return 0
        else:
            logger.error("创建房间失败，未找到房间窗口")
            dm.save_screenshot(label="test_host_create_room_failed", force=True)
            return 1

    except Exception as e:
        logger.exception(f"流程异常: {e}")
        return 1
    finally:
        dm.close()
        logger.complete()


if __name__ == "__main__":
    sys.exit(main())
