"""
自动采集战斗状态训练样本

利用帧差法 + 红色像素过滤自动标注：
- 帧差法检测到闪烁 + 红色像素 > 50 → 保存到 data/combat/
- 帧差法无闪烁 → 保存到 data/non_combat/

使用方法：
  uv run python scripts/collect_combat_samples.py --hero hxd
  uv run python scripts/collect_combat_samples.py --hero hxd --interval 2 --max 100

切换英雄后重新运行，指定 --hero 参数即可。
按 Ctrl+C 停止。
"""
import argparse
import os
import tempfile
import time

from PIL import Image

from GameBot.config import config
from GameBot.runner.driver import create_dm_client
from GameBot.utils import logger

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "combat_samples")


def main():
    parser = argparse.ArgumentParser(description="自动采集战斗状态训练样本")
    parser.add_argument("--hero", required=True, help="英雄名称（如 hxd、mk等）")
    parser.add_argument("--max", type=int, default=100, help="每个类别最大采集数量（默认100）")
    parser.add_argument("--interval", type=float, default=1.0, help="采集间隔秒数（默认1.0）")
    args = parser.parse_args()

    logger.info("===== 战斗样本自动采集 =====")
    logger.info(f"英雄: {args.hero}, 每类上限: {args.max}, 采集间隔: {args.interval}s")
    logger.info(f"数据目录: {DATA_DIR}")
    time.sleep(5)

    jiubing2_cfg = config.load_task("jiubing2")["jiubing2"]
    war3_cfg = config.get("war3", {})
    combat_cfg = jiubing2_cfg.get("combat_status", {})

    area = combat_cfg.get("in_combat_area_coords", [19, 56, 88, 103])
    frame_count = combat_cfg.get("frame_count", 10)
    frame_interval = combat_cfg.get("frame_interval", 0.3)
    diff_threshold = combat_cfg.get("diff_threshold", 30)
    changed_threshold = combat_cfg.get("changed_pixel_threshold", 20)

    combat_dir = os.path.join(DATA_DIR, "combat", args.hero)
    non_combat_dir = os.path.join(DATA_DIR, "non_combat", args.hero)
    os.makedirs(combat_dir, exist_ok=True)
    os.makedirs(non_combat_dir, exist_ok=True)

    combat_count = len([f for f in os.listdir(combat_dir) if f.endswith(".bmp")])
    non_combat_count = len([f for f in os.listdir(non_combat_dir) if f.endswith(".bmp")])
    logger.info(f"已有样本: combat={combat_count}, non_combat={non_combat_count}")

    dm = create_dm_client()
    hwnd = dm.get_active_window(
        war3_cfg["window_class"], war3_cfg["window_title"]
    )
    if not hwnd:
        logger.error("未找到 war3 窗口")
        return

    logger.info(f"已绑定窗口 hwnd={hwnd}")

    tmp_dir = tempfile.gettempdir()
    tmp_bmp = os.path.join(tmp_dir, "collect_combat_frame.bmp")

    with dm.bind_window(hwnd):
        client_size = war3_cfg.get("client_size", [1902, 1033])
        dm.set_client_size(hwnd, *client_size)
        logger.info("开始采集，按 Ctrl+C 停止...")

        try:
            while combat_count < args.max or non_combat_count < args.max:
                imgs, max_changed = _capture_frames(
                    dm, area, tmp_bmp, frame_count, frame_interval, diff_threshold
                )

                if imgs is None:
                    time.sleep(args.interval)
                    continue

                is_blinking = max_changed > changed_threshold

                if is_blinking and combat_count < args.max:
                    best_img = max(imgs, key=lambda im: _count_red_pixels(im))
                    red_count = _count_red_pixels(best_img)
                    if red_count > 50:
                        ts = time.strftime("%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
                        fname = f"{args.hero}_{ts}.bmp"
                        best_img.save(os.path.join(combat_dir, fname))
                        combat_count += 1
                        logger.info(
                            f"[combat] {fname} | 变化像素={max_changed} 红色像素={red_count} | "
                            f"combat={combat_count}/{args.max} non_combat={non_combat_count}/{args.max}"
                        )
                    else:
                        logger.debug(f"跳过 | 闪烁但无红色覆盖帧 变化像素={max_changed} 最大红色像素={red_count}")
                elif not is_blinking and non_combat_count < args.max:
                    red_count = _count_red_pixels(imgs[-1])
                    ts = time.strftime("%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
                    fname = f"{args.hero}_{ts}.bmp"
                    imgs[-1].save(os.path.join(non_combat_dir, fname))
                    non_combat_count += 1
                    logger.info(
                        f"[non_combat] {fname} | 变化像素={max_changed} 红色像素={red_count} | "
                        f"combat={combat_count}/{args.max} non_combat={non_combat_count}/{args.max}"
                    )
                else:
                    red_count = _count_red_pixels(imgs[-1])
                    logger.debug(
                        f"跳过 | 闪烁={is_blinking} 变化像素={max_changed} 红色像素={red_count}"
                    )

                time.sleep(args.interval)
        except KeyboardInterrupt:
            logger.info("采集已停止")
        finally:
            if os.path.exists(tmp_bmp):
                os.remove(tmp_bmp)

    logger.info(f"采集完成: combat={combat_count}, non_combat={non_combat_count}")
    logger.info(f"样本目录: {DATA_DIR}")


def _capture_frames(dm, area, tmp_bmp, frame_count, frame_interval, diff_threshold):
    """截取多帧，返回 (imgs, max_changed)。imgs 为 PIL.Image 列表。失败返回 (None, 0)。"""
    x1, y1, x2, y2 = area
    imgs = []
    pixel_data = []

    for i in range(frame_count):
        for _ in range(3):
            if dm.capture_region(x1, y1, x2, y2, tmp_bmp):
                break
            time.sleep(0.05)
        else:
            logger.warning(f"第 {i} 帧截图失败")
            return None, 0
        img = Image.open(tmp_bmp).convert("RGB")
        imgs.append(img)
        pixel_data.append(list(img.getdata()))
        if i < frame_count - 1:
            time.sleep(frame_interval)

    max_changed = 0
    for i in range(1, len(pixel_data)):
        changed = 0
        for px1, px2 in zip(pixel_data[i - 1], pixel_data[i]):
            if abs(px1[0] - px2[0]) > diff_threshold or \
               abs(px1[1] - px2[1]) > diff_threshold or \
               abs(px1[2] - px2[2]) > diff_threshold:
                changed += 1
        if changed > max_changed:
            max_changed = changed

    return imgs, max_changed


def _count_red_pixels(img) -> int:
    """统计红色像素数量（R>100 且 G<=40 且 B<=40）。"""
    pixels = list(img.getdata())
    return sum(1 for r, g, b in pixels if r > 100 and g <= 40 and b <= 40)


if __name__ == "__main__":
    main()
