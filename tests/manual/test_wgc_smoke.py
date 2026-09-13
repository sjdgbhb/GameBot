"""WGC 截图冒烟测试：对任意可见顶级窗口建会话、取一帧、裁客户区、存盘。

用法：
    .venv\\Scripts\\python tests/manual/test_wgc_smoke.py [--title 子串] [--hwnd N] [--out path]
不传参数时用当前前台窗口。
"""

import argparse
import ctypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from GameBot.runner.driver.wgc_capture import WgcCapture  # noqa: E402

user32 = ctypes.windll.user32


def find_by_title(sub: str) -> int:
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if sub in buf.value:
                    found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(cb, 0)
    for h, t in found:
        print(f"  候选: hwnd={h} title={t!r}")
    return found[0][0] if found else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title")
    ap.add_argument("--hwnd", type=int)
    ap.add_argument("--out", default="logs/wgc_smoke.png")
    ap.add_argument("--frames", type=int, default=10, help="连续取帧次数（观察帧龄）")
    a = ap.parse_args()

    hwnd = a.hwnd or (find_by_title(a.title) if a.title else user32.GetForegroundWindow())
    print(f"目标 hwnd={hwnd}")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    cap = WgcCapture.acquire(hwnd, min_interval_ms=200)
    print(f"会话启动+首帧: {time.perf_counter() - t0:.3f}s")
    try:
        frame = cap.grab_window()
        print(f"整窗帧: {frame.shape[1]}x{frame.shape[0]} dtype={frame.dtype}")
        (ox, oy), (cw, ch) = cap._client_offset(frame)
        print(f"客户区偏移=({ox},{oy}) 客户区={cw}x{ch}")
        t0 = time.perf_counter()
        img = cap.grab_client((0, 0, cw, ch))
        print(f"grab_client 整客户区耗时 {1000 * (time.perf_counter() - t0):.2f}ms -> {img.shape}")
        cap.save(a.out, (0, 0, cw, ch))
        print(f"已存盘: {a.out}")
        for i in range(a.frames):
            time.sleep(0.25)
            age = time.monotonic() - cap._latest_ts
            print(f"  帧龄 {age * 1000:.0f}ms")
    finally:
        cap.release()


if __name__ == "__main__":
    main()
