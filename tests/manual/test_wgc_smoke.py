"""WGC 截图冒烟测试：对任意可见顶级窗口建会话、取一帧、裁客户区、存盘。

用法：
    .venv\\Scripts\\python tests/manual/test_wgc_smoke.py [--title 子串] [--hwnd N] [--out path]
    .venv\\Scripts\\python tests/manual/test_wgc_smoke.py --title "Warcraft III" --watch 600
不传参数时用当前前台窗口。

--watch N：持续 N 秒，每 0.25s 采一次"帧龄"并实际调用 grab_client（走完整
取帧→偏移→裁剪路径，帧流停止会抛 CaptureError）。样本同时写 stdout 和
logs/wgc_watch.log —— 锁屏/最小化期间控制台不可见，结束后看日志末尾即可。

运行带浮窗（同生产任务）：--delay 秒倒计时后开始，按 Num- 可随时停止。
"""

import argparse
import ctypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from GameBot.runner.driver.wgc_capture import WgcCapture  # noqa: E402
from GameBot.runner.ui import run_with_float_window  # noqa: E402
from GameBot.utils.exception_handler import CaptureError  # noqa: E402

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


def watch_frames(cap: WgcCapture, seconds: int, log_path: Path, client, stop_event=None):
    """每 0.25s 采样帧龄并实际 grab_client；样本写日志文件，锁屏/最小化后可回看。"""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    max_age = 0.0
    stall_since = None  # 帧流停止的起始时间戳（帧龄首次超阈值）
    errors = 0
    with log_path.open("w", encoding="utf-8") as f:
        def out(msg):
            line = f"{time.strftime('%H:%M:%S')} {msg}"
            print(line, flush=True)
            f.write(line + "\n")
            f.flush()

        out(f"watch 开始，时长 {seconds}s，stale 阈值 {cap._stale_timeout}s")
        while time.time() - start < seconds:
            if stop_event is not None and stop_event.is_set():
                out("收到停止信号，提前结束")
                break
            age = time.monotonic() - cap._latest_ts
            max_age = max(max_age, age)
            try:
                cap.grab_client(client)
                if stall_since is None and age > cap._stale_timeout:
                    stall_since = age
                elif stall_since is not None and age <= cap._stale_timeout:
                    out(f"  帧流恢复（此前停滞约 {stall_since:.1f}s）")
                    stall_since = None
            except CaptureError as e:
                errors += 1
                if stall_since is None:
                    stall_since = age
                    out(f"  帧流停止 → CaptureError: {e}")
            if int((time.time() - start) * 4) % 4 == 0:  # 每秒打一次
                out(f"  帧龄 {age * 1000:.0f}ms")
            time.sleep(0.25)
        out(f"watch 结束：最大帧龄 {max_age * 1000:.0f}ms，CaptureError 次数 {errors}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title")
    ap.add_argument("--hwnd", type=int)
    ap.add_argument("--out", default="logs/wgc_smoke.png")
    ap.add_argument("--frames", type=int, default=10, help="连续取帧次数（观察帧龄）")
    ap.add_argument("--watch", type=int, default=0, help="帧流监测秒数：每0.25s采样帧龄+grab_client，写 logs/wgc_watch.log")
    ap.add_argument("--delay", type=int, default=5, help="浮窗倒计时秒数（期间按 Num- 可直接退出）")
    a = ap.parse_args()

    def task(stop_event, progress_callback):
        hwnd = a.hwnd or (find_by_title(a.title) if a.title else user32.GetForegroundWindow())
        print(f"目标 hwnd={hwnd}")
        progress_callback(f"hwnd={hwnd}")
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)

        t0 = time.perf_counter()
        cap = WgcCapture.acquire(hwnd, min_interval_ms=200)
        print(f"会话启动+首帧: {time.perf_counter() - t0:.3f}s")
        try:
            frame = cap.grab_window()
            print(f"整窗帧: {frame.shape[1]}x{frame.shape[0]} dtype={frame.dtype}")
            (ox, oy), (cw, ch) = cap._client_offset(frame)
            print(f"客户区偏移=({ox},{oy}) 客户区={cw}x{ch}")

            if a.watch:
                watch_frames(cap, a.watch, log_path=Path("logs/wgc_watch.log"), client=(0, 0, cw, ch), stop_event=stop_event)
                return

            t0 = time.perf_counter()
            img = cap.grab_client((0, 0, cw, ch))
            print(f"grab_client 整客户区耗时 {1000 * (time.perf_counter() - t0):.2f}ms -> {img.shape}")
            cap.save(a.out, (0, 0, cw, ch))
            print(f"已存盘: {a.out}")
            for i in range(a.frames):
                if stop_event is not None and stop_event.is_set():
                    break
                time.sleep(0.25)
                age = time.monotonic() - cap._latest_ts
                print(f"  帧龄 {age * 1000:.0f}ms")
        finally:
            cap.release()

    run_with_float_window("WGC冒烟测试", task, countdown_seconds=a.delay)


if __name__ == "__main__":
    main()
