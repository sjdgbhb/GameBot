"""War3 后台绑定矩阵探针 — 逐个测试 mouse 模式的可绑定性与 dx2 截图。

用法：
    uv run python tests/manual/test_war3_bind_probe.py
    uv run python tests/manual/test_war3_bind_probe.py --delay 10

对每个候选 mouse 模式：
1. BindWindowEx(display=dx2, keypad=windows, public=dx.public.active.api, mode=4)
2. 绑定成功后 capture_region 取小区域，判断是否黑屏
3. 输出矩阵结果表，挑「绑定OK + 截图非黑」的组合去 war3.toml 配置

注意：脚本会反复绑定/解绑 war3 窗口，运行期间不要操作游戏。
"""

import argparse
import sys
import time
from pathlib import Path

from PIL import Image

from GameBot.config import config
from GameBot.runner.driver import create_dm_client
from GameBot.utils import logger, setup_log_file

OUT_DIR = Path("logs/diag_war3_bind_probe")

# 候选 mouse 模式：大漠文档 war3 类 DX 游戏常见组合
CANDIDATE_MICE = [
    "windows",
    "windows3",
    "dx.mouse.position.lock.api",
    "dx.mouse.position.lock.message",
    "dx.mouse.position.lock.api|dx.mouse.raw.input",
    "dx.mouse.position.lock.api|dx.mouse.position.lock.message|dx.mouse.state.message",
    "dx.mouse.position.lock.api|dx.mouse.position.lock.message|dx.mouse.state.message|dx.mouse.api|dx.mouse.raw.input",
    "dx.mouse.position.lock.api|dx.mouse.raw.input|dx.mouse.api|dx.mouse.cursor",
]


def is_blank(img_path: str) -> bool:
    try:
        mn, mx = Image.open(img_path).convert("L").getextrema()
        return mn == mx
    except Exception:
        return True


def find_war3(dm, war3_cfg: dict) -> int:
    for h in dm.enum_windows(war3_cfg["window_class"], war3_cfg["window_title"]):
        if dm.is_window_visible(h) and dm.get_window_class(h) == war3_cfg["window_class"]:
            return int(h)
    return 0


def probe(dm, hwnd: int, mouse: str, base_cfg: dict) -> tuple[str, str]:
    """绑定 + 截图探测，返回 (绑定结果, 截图结果)。"""
    display = base_cfg.get("display", "dx2")
    keypad = base_cfg.get("keypad", "windows")
    public = base_cfg.get("public", "")
    mode = base_cfg.get("mode", 4)
    try:
        ret = dm._com_call("BindWindowEx", hwnd, display, mouse, keypad, public, mode)
    except Exception as e:
        return f"异常: {type(e).__name__}", "-"
    if ret != 1:
        try:
            err = dm._com_call("GetLastError")
        except Exception:
            err = "?"
        return f"失败 ret={ret} err={err}", "-"

    # 已绑定：截图验证 display 通道（Capture 用客户区坐标）
    try:
        time.sleep(0.5)
        x1, y1, x2, y2 = dm.get_client_rect(hwnd)
        w, h = min(200, x2 - x1), min(200, y2 - y1)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        safe = mouse.replace("|", "+").replace(".", "_")
        path = str((OUT_DIR / f"{safe}.bmp").resolve())
        ok = dm.capture_region(0, 0, w, h, path)
        shot = "非黑" if ok and not is_blank(path) else ("黑屏" if ok else "capture失败")
    except Exception as e:
        shot = f"异常: {type(e).__name__}"
    finally:
        try:
            dm._com_call("UnBindWindow")
        except Exception:
            pass
    return "OK", shot


def main() -> int:
    parser = argparse.ArgumentParser(description="war3 后台绑定矩阵探针")
    parser.add_argument("--delay", type=int, default=5)
    args = parser.parse_args()

    setup_log_file("war3绑定矩阵探针")
    cfg = config.load_task("war3.jiubing2.tasks.atomic.blackstone_gate_harassment")
    war3_cfg = cfg.get("war3", {})
    base_cfg = dict(war3_cfg.get("bind", {}))
    logger.info(f"基准绑定配置: {base_cfg}")

    for i in range(args.delay, 0, -1):
        logger.info(f"{i} 秒后开始...")
        time.sleep(1)

    dm = create_dm_client()
    try:
        hwnd = find_war3(dm, war3_cfg)
        if not hwnd:
            logger.error("未找到 war3 窗口")
            return 1
        logger.info(f"war3 hwnd={hwnd}")

        print(f"\n{'mouse 模式':<90} {'绑定':<22} {'截图'}")
        print("-" * 130)
        for mouse in CANDIDATE_MICE:
            bind_res, shot_res = probe(dm, hwnd, mouse, base_cfg)
            print(f"{mouse:<90} {bind_res:<22} {shot_res}")
        print("-" * 130)
        print("挑「绑定OK + 截图非黑」的组合填入 war3.toml [this.bind_background].mouse")
        return 0
    finally:
        dm.close()


if __name__ == "__main__":
    sys.exit(main())
