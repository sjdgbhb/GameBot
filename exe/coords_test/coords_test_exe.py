"""坐标兼容性测试 EXE — 32 位 Python 3.8 + 大漠插件 COM

功能：重置 war3 窗口尺寸 → F1 居中英雄 → 框选英雄，供用户检查坐标是否兼容。
"""
import sys
import time
from pathlib import Path

# ===== 1. 确定路径 =====
if getattr(sys, 'frozen', False):
    EXE_DIR = Path(sys.executable).parent
    BUNDLED_DIR = Path(sys._MEIPASS) / 'config' / 'data'
else:
    EXE_DIR = Path(__file__).parent
    BUNDLED_DIR = EXE_DIR.parent / 'src' / 'GameBot' / 'config' / 'data'

# ===== 2. 初始化配置系统（必须在导入其他 GameBot 模块之前）=====
from GameBot.config import config

config.config_path = BUNDLED_DIR
config._project_root_override = EXE_DIR

# ===== 3. 导入业务模块 =====
from GameBot.utils import setup_global_exception_hook, logger
from GameBot.config import config as cfg_singleton
from GameBot.runner.dm_client import DmClient
from GameBot.runner.business.war3 import War3Business
from GameBot.runner.ui import run_with_float_window


# 硬编码 war3 配置（无需用户配置文件）
WAR3_CFG = {
    "window_class": "Warcraft III",
    "window_title": "Warcraft III",
    "client_size": [1902, 1033],
    "small_window_response_time": 0.5,
    "general_time": 0.3,
    "key_time": 0.1,
}

# 框选区域 [x1, y1, x2, y2]（客户区坐标，基于 1902x1033）
BOX_COORDS = [851, 416, 1051, 616]
HOLD_TIME = 5
INTERVAL_TIME = 2


def main():
    setup_global_exception_hook()
    logger.info("############################# 游戏中点我测试 #############################")
    logger.info(f"EXE 目录: {EXE_DIR}")

    dm_dll = EXE_DIR / "dm" / "dm.dll"
    if not dm_dll.exists():
        logger.error(f"大漠插件 DLL 不存在: {dm_dll}")
        logger.error("请确保 dm/dm.dll 文件与 游戏中点我测试.exe 在同一目录下")
        sys.exit(1)

    # 设置全局配置（DmClient 需要读取 dm.dll 路径）
    cfg_singleton._config.setdefault("dm", {})["dll_path"] = "dm"
    cfg_singleton._config.setdefault("paths", {})["resources_path"] = "resources"

    def task_func(stop_event, progress_callback):
        dm = DmClient()
        war3 = War3Business(dm, WAR3_CFG)

        hwnd = dm.get_active_window(
            WAR3_CFG.get("window_class", ""),
            WAR3_CFG.get("window_title", ""),
        )
        if not hwnd:
            progress_callback("未找到 war3 窗口，请先切换到魔兽窗口")
            return

        with dm.bind_window(hwnd):
            progress_callback("重置窗口尺寸...")
            war3.set_client_size(hwnd)
            x1, y1, x2, y2 = dm.get_client_rect(hwnd)
            actual_w, actual_h = x2 - x1, y2 - y1
            expected = WAR3_CFG.get("client_size", [1902, 1033])
            print(f"窗口客户区: ({x1}, {y1}) ~ ({x2}, {y2}), 尺寸 {actual_w}x{actual_h}")
            print(f"配置期望: {expected[0]}x{expected[1]}")
            print(f"大漠版本: {dm.version}")
            if actual_w != expected[0] or actual_h != expected[1]:
                print(f"⚠ 客户区尺寸不匹配！坐标可能偏移")
                progress_callback(f"⚠ 尺寸不匹配: 实际 {actual_w}x{actual_h} vs 期望 {expected[0]}x{expected[1]}")
            else:
                print(f"✓ 客户区尺寸匹配")
                progress_callback(f"✓ 尺寸匹配 {actual_w}x{actual_h}")
            print()

            round_num = 0
            while not stop_event.is_set():
                round_num += 1
                progress_callback(f"第 {round_num} 轮: 框选文本")

                # 手动框选（可被 stop_event 中断）
                general_time = WAR3_CFG.get("general_time", 0.3)
                dm.move_to(*BOX_COORDS[:2])
                time.sleep(general_time)
                dm.left_down()
                time.sleep(general_time)
                dm.move_to(*BOX_COORDS[2:])
                elapsed = 0.0
                while elapsed < HOLD_TIME and not stop_event.is_set():
                    time.sleep(0.1)
                    elapsed += 0.1
                dm.left_up()

                if stop_event.is_set():
                    break
                progress_callback(f"第 {round_num} 轮完成，{INTERVAL_TIME}s 后重复")
                elapsed = 0.0
                while elapsed < INTERVAL_TIME and not stop_event.is_set():
                    time.sleep(0.1)
                    elapsed += 0.1

            progress_callback("测试结束")
            print("测试结束")

    run_with_float_window("坐标兼容性测试", task_func, countdown_seconds=5)


if __name__ == "__main__":
    main()
