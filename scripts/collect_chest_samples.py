"""
宝箱自动截图收集脚本

自动每隔 5 秒截图一张，保存到 data/chest_samples/images/。
在游戏中摆放宝箱（尤其是重叠场景），脚本会持续截图。

使用方法：
  .venv-dm/Scripts/python.exe scripts/collect_chest_samples.py

按 Ctrl+C 停止。
"""
import os
import sys
import time
import random

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from GameBot.config import config
from GameBot.utils.logger import logger
from GameBot.runner.dm_client import DmClient

IMAGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "chest_samples", "images"
)
INTERVAL = random.randint(1,10)  # 截图间隔（秒）


def main():
    cfg = config.load_task("war3.jiubing2.tasks.others.patrol_loot")
    war3_cfg = config.get("war3", {})
    hwnd_title = war3_cfg.get("window_title", "Warcraft III")

    dm = DmClient()

    import win32gui

    hwnd = win32gui.FindWindow(None, hwnd_title)
    if not hwnd:
        logger.error(f"未找到游戏窗口: {hwnd_title}")
        sys.exit(1)

    dm.bind_window(hwnd)
    client_size = war3_cfg.get("client_size", [1902, 1033])

    # 设置窗口客户区大小
    dm.set_client_size(hwnd, client_size[0], client_size[1])
    logger.info(f"窗口客户区已设置为 {client_size[0]}x{client_size[1]}")

    os.makedirs(IMAGE_DIR, exist_ok=True)

    from PIL import Image

    existing = len([f for f in os.listdir(IMAGE_DIR) if f.endswith((".jpg", ".png", ".bmp"))])
    logger.info(f"宝箱自动截图收集工具")
    logger.info(f"  保存目录: {IMAGE_DIR}")
    logger.info(f"  已有截图: {existing} 张")
    logger.info(f"  截图间隔: {INTERVAL} 秒")
    logger.info(f"  请在游戏中摆放宝箱，按 Ctrl+C 停止")

    count = 0
    try:
        while True:
            ts = time.strftime("%Y%m%d%H%M%S", time.localtime())
            path = os.path.join(IMAGE_DIR, f"{ts}.jpg")
            tmp_bmp = os.path.join(os.environ.get("TEMP", "/tmp"), f"chest_cap_{ts}.bmp")
            for _ in range(3):
                if dm.capture_region(0, 0, client_size[0], client_size[1], tmp_bmp):
                    break
                time.sleep(0.05)
            else:
                logger.error("截图失败，跳过")
                time.sleep(INTERVAL)
                continue

            img = Image.open(tmp_bmp).convert("RGB")
            img.save(path, "JPEG", quality=95)
            if os.path.exists(tmp_bmp):
                os.remove(tmp_bmp)
            count += 1
            logger.info(f"截图 #{count}: {path}")
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        pass

    logger.info(f"收集完成，本次截图 {count} 张，目录共 {existing + count} 张")
    logger.info(f"下一步: 用 x-anylabeling 标注图片，标签保存到 data/chest_samples/labels/")


if __name__ == "__main__":
    main()
