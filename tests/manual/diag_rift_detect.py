"""裂隙找图诊断（只读，不绑定窗口、不注入输入）。

用法：游戏内把视角停在风龙裂隙附近，然后运行：
    uv run python tests/manual/diag_rift_detect.py

输出：
- boss_rift_coords 区域截图 + 周边更大范围截图（存到 %TEMP%/rift_diag/）
- rift.bmp 在区域内的最高匹配分数及多档 delta_color 结果
"""

import tempfile
import time
from pathlib import Path

import numpy as np
import win32gui
from PIL import Image

from GameBot.config import config
from GameBot.runner.driver.visual import VisualMixin, _parse_rgb
from GameBot.runner.driver.wgc_capture import WgcCapture


def find_war3_hwnd() -> int:
    hwnds = []

    def cb(hwnd, _):
        if win32gui.GetClassName(hwnd) == "Warcraft III" and win32gui.IsWindowVisible(hwnd):
            hwnds.append(hwnd)

    win32gui.EnumWindows(cb, None)
    return hwnds[0] if hwnds else 0


def main():
    cfg = config.load_task("war3.jiubing2.tasks.others.paladin_wind_dragon")
    npc = cfg["war3"]["jiubing2"]["scenes"]["wind_dragon"]["npcs"]["wind_dragon"]
    region = npc["boss_rift_coords"]
    image = cfg["war3"]["jiubing2"]["boss_rift"]["image"]

    hwnd = find_war3_hwnd()
    if not hwnd:
        print("未找到 War3 窗口")
        return
    print(f"hwnd={hwnd}")

    cap = WgcCapture.for_hwnd(hwnd)
    out = Path(tempfile.gettempdir()) / "rift_diag"
    out.mkdir(parents=True, exist_ok=True)

    # 区域截图 + 周边扩展区域截图（人工核对裂隙实际位置）
    reg = cap.grab_client_rgb(tuple(region))
    Image.fromarray(reg).save(out / "region.bmp")
    pad = 150
    wide = (
        max(0, region[0] - pad),
        max(0, region[1] - pad),
        min(1902, region[2] + pad),
        min(1033, region[3] + pad),
    )
    wide_img = cap.grab_client_rgb(wide)
    Image.fromarray(wide_img).save(out / "wide.bmp")
    print(f"截图已保存到 {out}（region.bmp={reg.shape}, wide.bmp={wide_img.shape} 区域{wide}）")

    tpl = np.array(Image.open("src/GameBot/resources/images/" + image).convert("RGB"))
    print(f"模板 {image} 尺寸: {tpl.shape[1]}x{tpl.shape[0]}")

    mixin = VisualMixin()
    for delta in ("000000", "101010", "202020", "303030", "404040"):
        scores = mixin._match_scores(reg, tpl, _parse_rgb(delta))
        best = float(scores.max())
        idx = np.unravel_index(int(np.argmax(scores)), scores.shape)
        print(f"delta_color={delta}: 最高匹配分数 {best:.3f} @ 区内({idx[1]},{idx[0]}) → 客户区({region[0]+idx[1]},{region[1]+idx[0]})")
        # 周边大范围也试一下（防区域配错）
        if wide_img.shape[0] >= tpl.shape[0]:
            scores_w = mixin._match_scores(wide_img, tpl, _parse_rgb(delta))
            bw = float(scores_w.max())
            iw = np.unravel_index(int(np.argmax(scores_w)), scores_w.shape)
            print(f"    大范围: 最高 {bw:.3f} @ 客户区({wide[0]+iw[1]},{wide[1]+iw[0]})")

    cap.close()


if __name__ == "__main__":
    main()
