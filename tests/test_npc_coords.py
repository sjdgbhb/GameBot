"""
测试 NPC 坐标准确性：点击小地图 → 鼠标移动到 coords → 观察是否到达目标位置。
用法：.venv-dm/Scripts/python.exe tests/test_npc_coords.py
"""
import time

from GameBot.config import config
from GameBot.runner import DmClient
from GameBot.runner.business.war3 import War3Business


def main():
    # 要测试的坐标
    mini_coords = [150,897]
    coords = [957,399]

    print(f"测试坐标：mini_coords={mini_coords}, coords={coords}")
    print("3 秒后开始，请切换到魔兽窗口...")
    time.sleep(3)

    cfg = config.load_task("war3.jiubing2.scenes.kami_village")
    # 合并 war3 配置（load_task 会自动展开 dependencies，kami_village 依赖 jiubing2 → war3 → base）
    if "war3" not in cfg:
        war3_cfg = config.load_task("war3")
        cfg.update(war3_cfg)
    dm = DmClient()
    war3_cfg = cfg.get("war3", {})
    war3 = War3Business(dm, war3_cfg)

    hwnd = dm.get_active_window(war3_cfg["window_class"], war3_cfg["window_title"])
    if not hwnd:
        print("未找到 war3 窗口，请先切换到魔兽窗口")
        return

    with dm.bind_window(hwnd):
        war3.set_client_size(hwnd)
        gt = war3_cfg.get("general_time", 0.3)

        # 1. 点击小地图
        print("点击小地图...")
        dm.move_to(*mini_coords)
        time.sleep(gt)
        dm.left_click()
        time.sleep(1.0)

        # 2. 鼠标移动到目标坐标
        print(f"鼠标移动到 coords={coords}...")
        dm.move_to(*coords)
        time.sleep(2.0)

        print("测试完成，请观察英雄是否到达目标位置")


if __name__ == "__main__":
    main()
