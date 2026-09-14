"""War3 后台绑定矩阵探针 — 逐个测试 mouse 模式的可绑定性与 dx2 截图。

用法：
    uv run python tests/manual/test_war3_bind_probe.py
    uv run python tests/manual/test_war3_bind_probe.py --delay 10
    uv run python tests/manual/test_war3_bind_probe.py --click
    uv run python tests/manual/test_war3_bind_probe.py --click 173,828,1158,314 --no-watch

对每个候选 mouse 模式：
1. 走生产 dm.bind_window 上下文绑定（_current_bind_hwnd 等内部状态与真实任务一致）
2. 绑定成功后 capture_region 取小区域，判断是否黑屏
3. 输出矩阵结果表，挑「绑定OK + 截图非黑」的组合去 war3.toml 配置

--click 追加目标选择态点击测试（与生产路径完全一致）：
- 值格式 miniX,miniY,targetX,targetY（小地图坐标+主屏目标坐标，均为客户区坐标），
  不带值时默认城门骚扰首个路线点 173,828,1158,314
- 绑定前先 war3.set_client_size 统一客户区尺寸（坐标体系前提，同生产任务入口）
- 每组绑定后调用生产 move_to_minimap_point(mode=1)：点小地图切视角 →
  move_to → A → left_click。判定目标：脚本操作的鼠标与系统鼠标互不影响
  （双向解耦），分三项检查——
  ①脚本→系统：点击期间 GetCursorPos 自动比对系统光标位移（应不动）
  ②系统→游戏：绑定态下晃动物理鼠标，游戏光标应不跟随（人工确认）
  ③注入有效：英雄应朝目标点攻击移动（人工确认）
  用于验证「按 A 后注入点击落在物理光标处（raw input 干扰）」这类目标
  选择态专属问题——普通截图/绑定测试覆盖不到。
- 默认同时启动并发截图线程，复刻 TextMonitor 的生产路径（WGC 取帧 + OCR，
  每 monitor_interval 秒一次，不碰大漠）；--capture-dm 改用旧的 dm.Capture
  压力（用于对照复现"截图撕开注入锁"的旧症状，验证完成后删除）；
  --no-watch 关闭并发截图，用于隔离「并发截图是否干扰注入输入」这一变量。

--wgc-dump：按生产 bind_cfg 绑定（dx2 挂钩态）后，用 WGC 抓一帧整窗 + prompt_text
  区域存到 logs/diag_war3_bind_probe/，目测客户区偏移与 OCR 区域是否正确，然后退出。

--mouse MODE：只测指定 mouse 模式（默认跑全部候选）。

运行带浮窗（同生产任务）：倒计时结束开始测试，按 Num- 可随时停止。
"""

import argparse
import os
import sys
import threading
import time
import uuid
from pathlib import Path

from PIL import Image

from GameBot.config import config
from GameBot.runner.business.war3 import War3Business
from GameBot.runner.driver import create_dm_client
from GameBot.runner.driver.wgc_capture import WgcCapture
from GameBot.runner.ui import run_with_float_window
from GameBot.utils import logger, setup_log_file
from GameBot.utils.exception_handler import DmError

OUT_DIR = Path("logs/diag_war3_bind_probe")


def _probe_dm_shot() -> str:
    """--capture-dm 压力线程的 dm.Capture 输出路径。"""
    import tempfile

    path = os.path.join(tempfile.gettempdir(), f"probe_watch_{os.getpid()}_{uuid.uuid4().hex}.bmp")
    return path

# 默认点击测试点：城门骚扰首个路线点「小道入口附近」（小地图 + 主屏目标坐标）
DEFAULT_CLICK = "173,828,1158,314"

# 候选 mouse 模式：大漠文档 war3 类 DX 游戏常见组合
# 注意：dx.mouse.raw.input / dx.mouse.input.lock.api2 / api3 / dx.mouse.cursor 均为收费功能，
# 免费版 BindWindowEx 会直接失败（ret=0），列入仅为确认版本差异。
CANDIDATE_MICE = [
    "windows",
    "windows3",
    "dx.mouse.position.lock.api",
    "dx.mouse.position.lock.message",
    # input.lock.api：封锁系统API锁定鼠标输入接口（未标收费，唯一可能覆盖前台 raw input 干扰的免费项）
    "dx.mouse.input.lock.api",
    # windows2（position.lock.api|position.lock.message|state.message）+ input.lock.api
    "dx.mouse.position.lock.api|dx.mouse.position.lock.message|dx.mouse.state.message|dx.mouse.input.lock.api",
    # 上一组合 + state.api：补 API 级按键状态锁（目标选择态 war3 可能走 GetAsyncKeyState 读按键）
    "dx.mouse.position.lock.api|dx.mouse.position.lock.message|dx.mouse.state.api|dx.mouse.state.message|dx.mouse.input.lock.api",
    # 上一组合 + dx.mouse.api：封锁系统API模拟 dx 鼠标输入（DirectInput 通道注入源）
    "dx.mouse.position.lock.api|dx.mouse.position.lock.message|dx.mouse.state.api|dx.mouse.state.message|dx.mouse.api|dx.mouse.input.lock.api",
    # 完整 dx 系（免费项全集）：再加输入焦点锁，对准官方 "dx" 组合减去收费项
    "dx.mouse.position.lock.api|dx.mouse.position.lock.message|dx.mouse.state.api|dx.mouse.state.message|dx.mouse.api|dx.mouse.focus.input.api|dx.mouse.focus.input.message|dx.mouse.input.lock.api",
    "dx.mouse.input.lock.api|dx.mouse.state.api",
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
    """枚举 war3 窗口；多开时打印候选详情，优先非最小化窗口，仍歧义则人工选择。

    注意：本机可能同时存在多个 Warcraft III 窗口（KK 会残留闲置 war3 进程），
    enum 顺序不稳定，随机绑错窗口会导致操作落到另一个游戏实例上——
    表现为"脚本注入全部落空 + 你看的窗口物理鼠标完全主导光标"。
    """
    import ctypes
    import ctypes.wintypes as wtypes

    user32 = ctypes.windll.user32
    candidates = []
    for h in dm.enum_windows(war3_cfg["window_class"], war3_cfg["window_title"]):
        h = int(h)
        if dm.is_window_visible(h) and dm.get_window_class(h) == war3_cfg["window_class"]:
            candidates.append(h)
    if not candidates:
        return 0
    if len(candidates) == 1:
        h = candidates[0]
        if user32.IsIconic(h):
            logger.warning(f"选中的 war3 窗口 hwnd={h} 处于最小化状态！dx2 绑定对最小化窗口无效，请恢复窗口后再测")
        return h

    # 多窗口：打印候选详情（hwnd/pid/最小化/窗口矩形/客户区尺寸）
    def _info(h):
        pid = wtypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        r = wtypes.RECT()
        user32.GetWindowRect(h, ctypes.byref(r))
        iconic = bool(user32.IsIconic(h))
        try:
            x1, y1, x2, y2 = dm.get_client_rect(h)
            client = f"{x2 - x1}x{y2 - y1}"
        except Exception:
            client = "?"
        return f"hwnd={h} pid={pid.value} {'最小化' if iconic else '正常'} rect=({r.left},{r.top},{r.right},{r.bottom}) 客户区={client}"

    logger.warning(f"发现 {len(candidates)} 个 war3 窗口:")
    for idx, h in enumerate(candidates):
        logger.warning(f"  [{idx}] {_info(h)}")
    # 只有一个非最小化窗口时直接用，否则人工确认
    alive = [h for h in candidates if not user32.IsIconic(h)]
    if len(alive) == 1:
        logger.warning(f"自动选择非最小化窗口 hwnd={alive[0]}")
        return alive[0]
    while True:
        v = input(f"存在 {len(alive)} 个非最小化 war3 窗口，输入要绑定的序号 [0-{len(candidates) - 1}]: ").strip()
        if v.isdigit() and 0 <= int(v) < len(candidates):
            return candidates[int(v)]
        print("输入无效")


def _get_cursor_pos() -> tuple[int, int]:
    """读取系统物理光标位置（用于判定脚本注入是否带动系统鼠标）。"""
    import ctypes
    import ctypes.wintypes as wtypes

    pt = wtypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def _start_capture_pressure(war3, ocr_cfg, interval: float, use_dm: bool, dm, stop_event=None):
    """启动并发截图线程，复刻 TextMonitor 的截图压力。

    use_dm=False（默认）：走生产路径 war3._ocr_region_text（WGC 取帧 + OCR），
    与任务运行时完全一致；失败直接打日志并继续（探针只复现压力）。
    use_dm=True：旧的 dm.Capture 压力（对照复现"截图撕开注入锁"的旧症状）。
    """
    evt = threading.Event()

    def _loop():
        while not evt.is_set():
            if stop_event is not None and stop_event.is_set():
                return
            try:
                if use_dm:
                    # 直接走大漠 Capture COM 原语复现旧症状（capture_to_temp 已是 WGC 实现）
                    p = _probe_dm_shot()
                    dm._com_call("Capture", *ocr_cfg["area_coords"], p)
                    if os.path.exists(p):
                        os.remove(p)
                else:
                    war3._ocr_region_text(ocr_cfg)
            except Exception as e:
                logger.debug(f"探针并发截图异常: {e}")
            evt.wait(interval)

    t = threading.Thread(target=_loop, daemon=True, name="ProbeCapturePressure")
    t.start()
    return evt, t


def probe(
    dm,
    war3: War3Business,
    hwnd: int,
    mouse: str,
    base_cfg: dict,
    click=None,
    watch_area=None,
    watch_interval: float = 0.2,
    capture_dm: bool = False,
    stop_event=None,
) -> tuple[str, str, dict]:
    """绑定 + 截图探测，返回 (绑定结果, 截图结果, 点击测试结论)。

    走生产 dm.bind_window 上下文（而非裸 BindWindowEx），保证 _current_bind_hwnd
    等内部状态与真实任务一致——capture_region 的 layered 分支判断依赖它。

    click=(mini_coords, target_coords) 时追加目标选择态点击测试，
    判定「脚本鼠标与系统鼠标互不影响」的三个维度：
    ①脚本→系统：点击序列前后用 GetCursorPos 自动比对系统光标位移（自动）
    ②系统→游戏：提示晃动物理鼠标，人工确认游戏光标不跟随（绑定态下人工）
    ③注入有效性：人工确认英雄朝目标点攻击移动
    watch_area 非空时点击期间并发截图（复刻任务的文字监测线程压力）。
    """
    # 直接复用生产 bind_cfg 只覆盖 mouse（含 bind_delay 等全部字段，与真实任务一致）
    bind_cfg = {**base_cfg, "mouse": mouse}
    verdict = {}
    try:
        ctx = dm.bind_window(hwnd, bind_cfg=bind_cfg)
        ctx.__enter__()
    except DmError as e:
        return f"失败 {e}", "-", verdict
    except Exception as e:
        return f"异常: {type(e).__name__}", "-", verdict

    try:
        time.sleep(0.5)
        x1, y1, x2, y2 = dm.get_client_rect(hwnd)
        w, h = min(200, x2 - x1), min(200, y2 - y1)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        safe = mouse.replace("|", "+").replace(".", "_")
        path = str((OUT_DIR / f"{safe}.bmp").resolve())
        ok = dm.capture_region(0, 0, w, h, path)
        shot = "非黑" if ok and not is_blank(path) else ("黑屏" if ok else "capture失败")
        if click:
            mini_coords, target_coords = click
            watch_evt = None
            if watch_area:
                watch_evt, _ = _start_capture_pressure(
                    war3, watch_area, watch_interval, capture_dm, dm, stop_event
                )
            try:
                # 检查②：系统→游戏方向隔离（绑定态下、脚本无操作时晃动物理鼠标）
                input("  [绑定中] 请晃动你的物理鼠标后回车——游戏光标是否跟随了物理鼠标？ ")
                verdict["follow"] = input("    游戏光标跟随物理鼠标？[y=跟随(坏)/回车=不跟随(好)]: ").strip().lower()
                # 检查①③：脚本→系统方向隔离 + 注入有效性
                print("  下面发 A+左键，期间请勿动鼠标（自动检测系统光标是否被带动）")
                pos_before = _get_cursor_pos()
                # 右键复位：取消可能残留的"选择目标"态
                dm.move_to(*target_coords)
                dm.right_click()
                time.sleep(war3.war3_cfg["general_time"])
                # 与生产 _clear_route 一致：F1 → 小地图切视角 → A+左键
                dm.key_press_char("F1")
                time.sleep(war3.war3_cfg["general_time"])
                war3.move_to_minimap_point(
                    list(mini_coords),
                    list(target_coords),
                    mode=1,
                    wait_time=2.0,  # 留出观察英雄是否开始移动的时间
                    stop_event=stop_event,
                )
                pos_after = _get_cursor_pos()
                verdict["sys_delta"] = (pos_after[0] - pos_before[0], pos_after[1] - pos_before[1])
                verdict["move"] = input("    英雄是否朝目标点攻击移动？[y/n]: ").strip().lower()
            finally:
                if watch_evt is not None:
                    watch_evt.set()
            shot += "+已点击"
    except Exception as e:
        shot = f"异常: {type(e).__name__}"
    finally:
        try:
            ctx.__exit__(None, None, None)
        except Exception:
            pass
    return "OK", shot, verdict


def _wgc_dump(dm, war3: War3Business, hwnd: int, base_cfg: dict, ocr_cfg: dict):
    """dx2 绑定态下用 WGC 抓整窗 + OCR 区域存盘，验证客户区偏移是否正确。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with dm.bind_window(hwnd, bind_cfg=base_cfg):
        cap = WgcCapture.acquire(hwnd, min_interval_ms=200)
        try:
            frame = cap.grab_window()
            (ox, oy), (cw, ch) = cap._client_offset(frame)
            print(f"WGC 整窗帧 {frame.shape[1]}x{frame.shape[0]}，客户区偏移=({ox},{oy})，客户区={cw}x{ch}")
            cap.save(str((OUT_DIR / "wgc_full.png").resolve()))
            area = tuple(ocr_cfg["area_coords"])
            cap.save(str((OUT_DIR / "wgc_prompt_area.png").resolve()), area)
            print(f"已存盘: {OUT_DIR}/wgc_full.png, wgc_prompt_area.png —— 请目测 prompt 区域内容")
        finally:
            cap.release()


def main() -> int:
    parser = argparse.ArgumentParser(description="war3 后台绑定矩阵探针")
    parser.add_argument("--delay", type=int, default=5, help="浮窗倒计时秒数")
    parser.add_argument(
        "--click",
        type=str,
        nargs="?",
        const=DEFAULT_CLICK,
        default=None,
        metavar="MX,MY,X,Y",
        help="目标选择态点击测试：绑定后走生产 move_to_minimap_point 发 A+左键"
        "（小地图坐标 + 主屏目标坐标，客户区坐标；不带值默认城门骚扰首点 173,828,1158,314）",
    )
    parser.add_argument(
        "--no-watch",
        action="store_true",
        help="点击测试时不启动并发截图线程（默认开启，复刻任务监测线程的截图压力）",
    )
    parser.add_argument(
        "--capture-dm",
        action="store_true",
        help="并发截图压力改用旧的 dm.Capture（对照复现旧症状，验证完成后删除此选项）",
    )
    parser.add_argument(
        "--wgc-dump",
        action="store_true",
        help="按生产 bind_cfg 绑定（dx2 挂钩态）后用 WGC 抓整窗 + prompt_text 区域存盘，目测后退出",
    )
    parser.add_argument(
        "--mouse",
        type=str,
        default=None,
        help="只测指定 mouse 模式（默认跑全部候选）",
    )
    args = parser.parse_args()
    click = None
    if args.click is not None:
        try:
            vals = [int(v) for v in args.click.split(",")]
            if len(vals) != 4:
                raise ValueError
            click = (vals[:2], vals[2:])
        except ValueError:
            logger.error(f"--click 参数格式错误: {args.click!r}，应为 miniX,miniY,targetX,targetY")
            return 1

    setup_log_file("war3绑定矩阵探针")
    cfg = config.load_task("war3.jiubing2.tasks.atomic.blackstone_gate_harassment")
    war3_cfg = cfg.get("war3", {})
    base_cfg = dict(war3_cfg.get("bind", {}))
    # 并发截图线程复刻任务监测线程：同区域（prompt_text）、同间隔（monitor_interval）
    watch_ocr_cfg = cfg.get("prompt_text")
    watch_interval = cfg.get("atomic_task", {}).get("monitor_interval", 0.2)
    logger.info(
        f"基准绑定配置: {base_cfg}，监测区域: {watch_ocr_cfg.get('area_coords')}，间隔: {watch_interval}s，"
        f"截图: {'dm.Capture(旧)' if args.capture_dm else 'WGC(生产)'}"
    )
    mice = [args.mouse] if args.mouse else CANDIDATE_MICE

    def task_wrapper(stop_event, progress_callback=None):
        dm = create_dm_client()
        war3 = None
        try:
            war3 = War3Business(dm, war3_cfg)
            hwnd = find_war3(dm, war3_cfg)
            if not hwnd:
                logger.error("未找到 war3 窗口")
                return
            logger.info(f"war3 hwnd={hwnd}")
            # 尺寸统一放在绑定前：坐标均按 client_size 标定，且 dx2 挂钩后
            # resize 会重建交换链导致闪屏（同生产任务入口顺序）
            war3.set_client_size(hwnd)

            if args.wgc_dump:
                _wgc_dump(dm, war3, hwnd, base_cfg, watch_ocr_cfg)
                return

            print(f"\n{'mouse 模式':<90} {'绑定':<22} {'截图'}")
            print("-" * 130)
            if click:
                print("判定标准：脚本操作的鼠标与系统鼠标互不影响（双向解耦）")
                print("  ①脚本→系统：A+点击期间系统光标不动（自动检测）")
                print("  ②系统→游戏：晃动物理鼠标时游戏光标不跟随（人工确认）")
                print("  ③注入有效：英雄朝目标点攻击移动（人工确认）")
            for i, mouse in enumerate(mice, 1):
                if stop_event is not None and stop_event.is_set():
                    break
                if progress_callback:
                    progress_callback(f"探针 {i}/{len(mice)}")
                bind_res, shot_res, verdict = probe(
                    dm,
                    war3,
                    hwnd,
                    mouse,
                    base_cfg,
                    click=click,
                    watch_area=watch_ocr_cfg if (click and not args.no_watch) else None,
                    watch_interval=watch_interval,
                    capture_dm=args.capture_dm,
                    stop_event=stop_event,
                )
                line = f"{mouse:<90} {bind_res:<22} {shot_res}"
                if verdict:
                    dx, dy = verdict.get("sys_delta", (0, 0))
                    sys_ok = "OK" if abs(dx) <= 2 and abs(dy) <= 2 else f"FAIL 位移({dx},{dy})"
                    move_ok = verdict.get("move") == "y"
                    follow = verdict.get("follow") == "y"
                    print(
                        f"{line} | ①脚本→系统:{sys_ok} ②系统→游戏:{'FAIL' if follow else 'OK'}"
                        f" ③移动:{'OK' if move_ok else 'FAIL'}"
                    )
                else:
                    print(line)
                if click and verdict:
                    if input("  继续下一组？[回车=继续/q=中止]: ").strip().lower() == "q":
                        break
            print("-" * 130)
            print("挑「绑定OK + 截图非黑 + ①②③全OK」的组合填入 war3.toml [this.bind_background].mouse")
        finally:
            if war3 is not None:
                war3.release_wgc()
            dm.close()

    run_with_float_window(
        "war3绑定矩阵探针",
        task_wrapper,
        countdown_seconds=args.delay,
        float_cfg=cfg.get("float_window", {}),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
