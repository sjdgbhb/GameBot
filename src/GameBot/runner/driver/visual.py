"""视觉操作 Mixin — 找图找色、截图（基于 WGC 帧的 numpy 实现）。

所有截图统一走 Windows Graphics Capture（WGC），不再使用大漠 Capture 或
PrintWindow。坐标均为**绑定窗口客户区坐标**（与大漠 FindPic 语义一致）。

模板匹配语义与大漠对齐：
- delta_color "RRGGBB"：每通道允许的颜色偏差（大漠颜色串为 RGB 序）
- sim：相似度阈值，等于"模板中容差内像素占比"的最小值
- find_pic 返回 (index, x, y)：index=0 命中 / -1 未命中；x,y 为命中图片
  左上角的**客户区绝对坐标**（搜索区偏移 + 区内偏移）
"""

import time
from typing import List, Tuple

import numpy as np
from PIL import Image

from GameBot.runner.driver.wgc_capture import WgcCapture
from GameBot.runner.resource_manager import res_mgr
from GameBot.utils.exception_handler import CaptureError
from GameBot.utils.logger import logger


def _parse_rgb(hex_color: str) -> Tuple[int, int, int]:
    """解析大漠颜色串 "RRGGBB" 为 (R, G, B) 通道容差/颜色值。"""
    s = hex_color.strip().lstrip("#").lower()
    if len(s) != 6:
        raise ValueError(f"颜色格式错误（应为6位十六进制 RRGGBB）: {hex_color!r}")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


class VisualMixin:
    """视觉相关操作：找图、找色、截图。

    依赖子类提供 `_current_bind_hwnd`（bind_window 上下文内由 WindowMixin 设置）。
    """

    # ── WGC 会话 ─────────────────────────────────────────

    def _wgc(self) -> WgcCapture:
        """当前绑定窗口的 WGC 常驻会话；未绑定直接报错（不做前台/其他回退）。"""
        hwnd = getattr(self, "_current_bind_hwnd", 0)
        if not hwnd:
            raise CaptureError("当前未绑定窗口（_current_bind_hwnd=0），无法用 WGC 取帧")
        return WgcCapture.for_hwnd(hwnd)

    # ── 模板匹配 ─────────────────────────────────────────

    @staticmethod
    def _match_scores(region: np.ndarray, tpl: np.ndarray, tol: Tuple[int, int, int]) -> np.ndarray:
        """计算每个位置"模板像素全部落在容差内"的比例，返回 (ph, pw) 分数图。

        region/tpl 均为 RGB 三通道 uint8。按位置行分块计算，控制内存。
        """
        rh, rw = region.shape[:2]
        th, tw = tpl.shape[:2]
        ph, pw = rh - th + 1, rw - tw + 1
        scores = np.zeros((ph, pw), dtype=np.float32)
        tol_arr = np.asarray(tol, dtype=np.int16)
        tpl_i16 = tpl.astype(np.int16)
        # 每块处理的"位置行"数：约 64MB 的 int16 上限
        rows_per_chunk = max(1, int(32 * 1024 * 1024 // max(1, pw * th * tw * 3)))
        for y0 in range(0, ph, rows_per_chunk):
            y1 = min(y0 + rows_per_chunk, ph)
            # 滑窗视图：(chunk_rows, pw, 3, th, tw) → 调整轴序为 (chunk_rows, pw, th, tw, 3)
            win = np.lib.stride_tricks.sliding_window_view(
                region[y0 : y0 + th + (y1 - y0) - 1], (th, tw), axis=(0, 1)
            ).transpose(0, 1, 3, 4, 2)
            ok = (np.abs(win.astype(np.int16) - tpl_i16) <= tol_arr).all(axis=-1)
            scores[y0:y1] = ok.mean(axis=(-1, -2))
        return scores

    _TPL_CACHE: dict = {}

    def _load_template(self, pic_name: str) -> np.ndarray:
        """加载模板图片为 RGB ndarray（带缓存）。"""
        path = res_mgr.get_image_path(pic_name)
        tpl = self._TPL_CACHE.get(path)
        if tpl is None:
            tpl = np.array(Image.open(path).convert("RGB"))
            self._TPL_CACHE[path] = tpl
        return tpl

    # ── 找图 ─────────────────────────────────────────────

    def find_pic(self, x1, y1, x2, y2, pic_name, sim=0.9, delta_color="000000", dir=0) -> Tuple[int, int, int]:
        """找图，返回 (index, x, y)。index=0 命中，-1 未命中；x,y 为命中图左上角客户区坐标。

        与大漠 FindPic 语义一致：delta_color 每通道容差，sim 为容差内像素占比阈值。
        dir 仅支持 0（左上→右下扫描序的第一个命中，取分数最高者）。
        """
        region = self._wgc().grab_client_rgb((x1, y1, x2, y2))
        tpl = self._load_template(pic_name)
        if tpl.shape[0] > region.shape[0] or tpl.shape[1] > region.shape[1]:
            return -1, -1, -1
        scores = self._match_scores(region, tpl, _parse_rgb(delta_color))
        best = np.unravel_index(int(np.argmax(scores)), scores.shape)
        if float(scores[best]) >= sim:
            return 0, x1 + int(best[1]), y1 + int(best[0])
        return -1, -1, -1

    def click_pic(self, pic_name, x1=0, y1=0, x2=1920, y2=1080, delta_color="000000", sim=0.9, offset_x=0, offset_y=0):
        """点击图片中心（偏移后）"""
        is_found, x, y = self.find_pic(x1, y1, x2, y2, pic_name, delta_color, sim)
        if is_found < 0:
            return False
        click_x = x + offset_x
        click_y = y + offset_y
        self._com_call("MoveTo", click_x, click_y)
        self._com_call("LeftClick")
        logger.info(f"点击图片: {pic_name} 坐标({click_x},{click_y})")
        return True

    def find_pics(self, x1, y1, x2, y2, pic_names, delta_color="000000", sim=0.9, dir=0) -> List[Tuple[int, int, int]]:
        """多模板找图，返回 [(index, x, y), ...]（index 为模板序号），空则返回 []。"""
        region = self._wgc().grab_client_rgb((x1, y1, x2, y2))
        tol = _parse_rgb(delta_color)
        matches = []
        for idx, name in enumerate(pic_names.split("|")):
            tpl = self._load_template(name)
            if tpl.shape[0] > region.shape[0] or tpl.shape[1] > region.shape[1]:
                continue
            scores = self._match_scores(region, tpl, tol)
            best = np.unravel_index(int(np.argmax(scores)), scores.shape)
            if float(scores[best]) >= sim:
                matches.append((idx, x1 + int(best[1]), y1 + int(best[0])))
        return matches

    # ── 找色 ─────────────────────────────────────────────

    def find_color(self, x1, y1, x2, y2, color="ff0000-000000", sim=0.9, dir=0) -> Tuple[int, int, int]:
        """找色，返回 (是否找到, x, y)。

        color 格式 "RRGGBB-DDGGBB"（大漠语义：目标色-每通道偏色，RGB 序）。
        命中条件：搜索区内存在像素，其三通道与目标色各差值 ≤ 容差。
        容差取值：偏色 delta 非 0 时用 delta；delta 为 0 时用 (1-sim)*255 推导
        （与大漠"无偏色时 sim 控制色差范围"的行为一致）。
        """
        if "-" in color:
            target_hex, delta_hex = color.split("-", 1)
        else:
            target_hex, delta_hex = color, "000000"
        tr, tg, tb = _parse_rgb(target_hex)
        dr, dg, db = _parse_rgb(delta_hex)
        if dr == 0 and dg == 0 and db == 0:
            tol = round((1.0 - sim) * 255)
            dr = dg = db = tol
        region = self._wgc().grab_client_rgb((x1, y1, x2, y2)).astype(np.int16)
        mask = (
            (np.abs(region[..., 0] - tr) <= dr)
            & (np.abs(region[..., 1] - tg) <= dg)
            & (np.abs(region[..., 2] - tb) <= db)
        )
        ys, xs = np.nonzero(mask)
        if len(xs) == 0:
            return 0, -1, -1
        # dir=0：左上→右下扫描序第一个命中
        return 1, x1 + int(xs[0]), y1 + int(ys[0])

    def get_color(self, x: int, y: int) -> str:
        """获取指定客户区坐标像素颜色（"RRGGBB" 六位十六进制，RGB 序，与大漠一致）。"""
        px = self._wgc().grab_client_rgb((x, y, x + 1, y + 1))[0, 0]
        return f"{int(px[0]):02x}{int(px[1]):02x}{int(px[2]):02x}"

    # ── 截图 ─────────────────────────────────────────────

    def capture_region(self, x1, y1, x2, y2, filepath: str) -> bool:
        """截取客户区区域到文件，返回是否成功。需在窗口绑定上下文内调用。"""
        img = self._wgc().grab_client((x1, y1, x2, y2))[:, :, [2, 1, 0]]
        Image.fromarray(img).save(filepath)
        return True

    def wait_pic(self, pic_name, x1=0, y1=0, x2=1920, y2=1080, timeout=10, interval=0.5, **kwargs):
        """等待图片出现，默认全屏查找"""
        start = time.time()
        while time.time() - start < timeout:
            found, _, _ = self.find_pic(x1, y1, x2, y2, pic_name, **kwargs)
            if found >= 0:
                return True
            time.sleep(interval)
        logger.warning(f"等待图片超时: {pic_name}")
        return False
