"""
跳刀目标坐标测试：移动到指定坐标 → 按快捷键 → 点击，验证跳刀落点是否正确。
用法：切到魔兽窗口后运行 .venv-dm/Scripts/python.exe tests/test_jump_knife.py
"""
import time

from GameBot.config import config
from GameBot.runner import DmClient
from GameBot.utils.logger import logger


def main():
    # 从配置读取跳刀快捷键和目标坐标
    cfg = config.load_task("war3.jiubing2.tasks.others.patrol_loot")
    hero_cfg = cfg.get("hero", {})
    war3_cfg = cfg.get("war3", {})

    # 找跳刀快捷键
    hotkey = ""
    for item in hero_cfg.get("inventory", []):
        if item.get("id") == 6:
            hotkey = item.get("hotkey", "")
            break
    if not hotkey:
        logger.error("未在物品栏配置中找到跳刀（id=6）")
        return

    # 从荒漠废墟路线的跳刀 action 读取目标坐标
    patrol_cfg = cfg["war3"]["jiubing2"]["tasks"]["others"]["patrol_loot"]
    jump_coords = None
    for preset in patrol_cfg.get("route_presets", []):
        if preset.get("name") != "荒漠废墟":
            continue
        for pt in preset.get("points", []):
            for act in pt.get("actions", []):
                if act.get("type") == "item" and act.get("id") == 6:
                    jump_coords = act.get("coords")
                    break
    if not jump_coords:
        logger.error("未在荒漠废墟路线中找到跳刀 action 的 coords")
        return

    key_time = war3_cfg.get("key_time", 0.1)
    logger.info(f"跳刀快捷键：{hotkey}，目标坐标：{jump_coords}，key_time={key_time}")

    logger.info("请切到 war3 窗口，5 秒后开始查找窗口并测试...")
    time.sleep(5)

    dm = DmClient()
    hwnd = dm.get_active_window(war3_cfg["window_class"], war3_cfg["window_title"])
    if not hwnd:
        logger.error("未找到 war3 窗口")
        return

    with dm.bind_window(hwnd):
        # 测试 3 次
        for i in range(3):
            logger.info(f"--- 第 {i+1} 次测试 ---")
            logger.info(f"移动到 {jump_coords}")
            dm.move_to(*jump_coords)
            time.sleep(0.5)
            logger.info(f"按键 {hotkey}")
            dm.key_press_char(hotkey)
            time.sleep(key_time)
            logger.info("点击")
            dm.left_click()
            time.sleep(30)  # 等待跳刀动画完成，观察落点
            logger.info(f"第 {i+1} 次测试完成，观察英雄落点是否正确")

    logger.info("测试结束")


if __name__ == "__main__":
    main()
