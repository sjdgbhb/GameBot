"""测试大漠后台键鼠在 KK 主界面的兼容性。

流程：
1. 等待 N 秒（默认 5 秒），方便用户提前打开 KK 主界面。
2. 从配置读取 KK 窗口类名、标题、客户区尺寸、搜索坐标、地图名。
3. 枚举并找到 KK 主界面窗口，对齐客户区尺寸。
4. 遍历不同的 mouse/keypad 大漠绑定组合：
   - 每种组合单独绑定窗口
   - 点击搜索输入框 → 清空 → 输入地图名
   - 点击搜索图标
   - 等待搜索结果
   - 截图搜索结果区域并 OCR
5. 输出每种组合是否成功，并保存截图。

用法：
    uv run python tests/manual/test_dm_input_kk.py
    uv run python tests/manual/test_dm_input_kk.py --map-name "九种兵器2" --delay 5
    uv run python tests/manual/test_dm_input_kk.py --mouse windows3 --keypad windows

配置来源：
- src/GameBot/config/data/kk.toml
- src/GameBot/config/data/war3/jiubing2/jiubing2.toml
"""

import argparse
import sys
import time
from pathlib import Path

from PIL import Image

from GameBot.config import config
from GameBot.inference import get_inference_client
from GameBot.runner.driver import create_dm_client
from GameBot.utils import DmError, logger, setup_log_file

OUT_DIR = Path("logs/diag_dm_input")


# 默认测试矩阵（display 固定 gdi，mode 默认 0）。
# dx/windows2 系列需要管理员权限，未提权时 BindWindow 会失败，脚本会记录失败并继续。
DEFAULT_MOUSE_MODES = ["windows", "windows3", "windows2", "dx", "dx2"]
DEFAULT_KEYPAD_MODES = ["windows", "dx"]
DEFAULT_MODES = [0]


def find_hall_window(dm, window_class: str, window_title: str) -> int:
    """按类名+标题查找可见的 KK 主界面窗口。"""
    for h in dm.enum_windows(window_class, window_title, filter=1 + 2 + 8 + 16):
        if not dm.is_window_visible(h):
            continue
        if dm.get_window_class(h) != window_class:
            continue
        if window_title and dm.get_window_title(h) != window_title:
            continue
        return int(h)
    return 0


def is_blank_image(img_path: str) -> bool:
    """判断图片是否为纯色（黑屏/白屏），用于排除无效截图。"""
    try:
        mn, mx = Image.open(img_path).convert("L").getextrema()
        return mn == mx
    except Exception:
        return False


def build_test_cases(mouse_modes, keypad_modes, modes, display: str = "gdi") -> list:
    """构建大漠绑定组合测试列表。"""
    cases = []
    for mode in modes:
        for mouse in mouse_modes:
            for keypad in keypad_modes:
                cases.append({
                    "display": display,
                    "mouse": mouse,
                    "keypad": keypad,
                    "mode": mode,
                    "bind_delay": 1.0,
                })
    return cases


def ocr_result_texts(inf, img_path: str) -> list:
    """对截图 OCR 并返回文本列表。"""
    try:
        lines = inf.ocr_lines_from_file(img_path)
        return [ln.get("text", "").strip() for ln in lines if ln.get("text", "").strip()]
    except Exception as e:
        logger.warning(f"OCR 失败: {e}")
        return []


def test_input_case(
    dm,
    hwnd: int,
    main_cfg: dict,
    map_name: str,
    keyword: str,
    case_cfg: dict,
    label: str,
    inf,
) -> dict:
    """对一种 mouse/keypad 组合执行完整输入流程，返回结果摘要。"""
    result = {
        "case": case_cfg,
        "bind_ok": False,
        "input_ok": False,
        "search_ok": False,
        "keyword_found": False,
        "screenshot": "",
        "ocr_texts": [],
    }

    search_input = main_cfg.get("search_input_coords", [0, 0])
    search_icon = main_cfg.get("search_map_coords", [0, 0])
    search_wait = main_cfg.get("search_map_wait_time", 5)
    result_area = main_cfg.get("map_result_ocr_area_coords", [0, 0, 0, 0])

    if not search_input or not search_icon or not result_area:
        logger.error("  配置中缺少搜索坐标或结果区域")
        return result

    result_path = (OUT_DIR / f"{label}_result.bmp").resolve()

    try:
        with dm.bind_window(hwnd, bind_cfg=case_cfg):
            result["bind_ok"] = True
            logger.info(f"  [{label}] 已绑定，开始输入流程")

            # 1. 点击搜索输入框
            dm.move_to(*search_input)
            time.sleep(0.3)
            dm.left_click()
            time.sleep(0.2)

            # 2. 清空已有内容：End 移到末尾，多次退格后再 Ctrl+A 兜底删除
            dm.key_press_char("end")
            time.sleep(0.2)
            for _ in range(30):
                dm.key_press_char("back")
                time.sleep(0.01)
            dm.key_press_char("ctrl+a")
            time.sleep(0.2)
            dm.key_press_char("back")
            time.sleep(0.2)

            # 3. 输入地图名
            dm.send_string2(map_name, hwnd=hwnd)
            time.sleep(0.3)
            logger.info(f"  [{label}] 已输入地图名: {map_name}")

            # 4. 点击搜索图标
            dm.move_to(*search_icon)
            time.sleep(0.3)
            dm.left_click()
            logger.info(f"  [{label}] 已点击搜索图标")

            # 5. 等待搜索结果
            time.sleep(search_wait)

            # 6. 截图搜索结果区域
            if result_area[2] > result_area[0] and result_area[3] > result_area[1]:
                ok = dm.capture_region(
                    result_area[0],
                    result_area[1],
                    result_area[2],
                    result_area[3],
                    str(result_path),
                )
                if ok and not is_blank_image(str(result_path)):
                    result["search_ok"] = True
                    result["screenshot"] = str(result_path)
                    result["ocr_texts"] = ocr_result_texts(inf, str(result_path))
                    all_text = "".join(result["ocr_texts"])
                    result["keyword_found"] = keyword in all_text
                    logger.info(f"  [{label}] OCR 结果: {result['ocr_texts']}")
                    if result["keyword_found"]:
                        logger.info(f"  [{label}] 搜索成功，识别到关键词 '{keyword}'")
                    else:
                        logger.warning(f"  [{label}] 未识别到关键词 '{keyword}'，完整文本: {all_text}")
                else:
                    logger.warning(f"  [{label}] 搜索结果区域截图失败或为空")

            # 输入流程完成
            result["input_ok"] = True
    except DmError as e:
        logger.warning(f"  [{label}] 绑定或输入失败: {e}")
    except Exception as e:
        logger.error(f"  [{label}] 异常: {e}")

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="KK 主界面大漠后台键鼠兼容性测试")
    parser.add_argument("--delay", type=int, default=5, help="启动前等待秒数（默认 5）")
    parser.add_argument("--map-name", type=str, default=None, help="搜索的地图名（默认读取 jiubing2.toml）")
    parser.add_argument("--keyword", type=str, default=None, help="用于验证搜索结果的关键词（默认与地图名相同）")
    parser.add_argument("--mouse", type=str, default=None, help="只测试指定的鼠标模式，多个用逗号分隔")
    parser.add_argument("--keypad", type=str, default=None, help="只测试指定的键盘模式，多个用逗号分隔")
    parser.add_argument("--mode", type=int, default=None, help="只测试指定的 mode（默认 0）")
    parser.add_argument("--display", type=str, default="gdi", help="截图模式（默认 gdi）")
    args = parser.parse_args()

    setup_log_file("kk主界面键鼠兼容性")
    logger.info("=" * 60)
    logger.info("KK 主界面大漠后台键鼠兼容性测试")
    logger.info("=" * 60)

    # 倒计时
    for i in range(args.delay, 0, -1):
        logger.info(f"{i} 秒后开始...")
        time.sleep(1)

    # 加载配置
    kk_cfg = config.load_task("kk").get("kk", {})
    window_class = kk_cfg.get("window_class", "")
    window_title = kk_cfg.get("window_title", "")
    main_cfg = kk_cfg.get("main", {})
    main_size = tuple(main_cfg.get("window_size", [1332, 945]))

    # 地图名默认从 jiubing2 配置读取
    map_name = args.map_name
    if not map_name:
        try:
            jiubing2_cfg = config.load_task("jiubing2")
            map_name = jiubing2_cfg.get("game", {}).get("map_name", "九种兵器2诸神战场")
        except Exception:
            map_name = "九种兵器2诸神战场"
    keyword = args.keyword or map_name

    logger.info(f"KK 窗口类名: {window_class}")
    logger.info(f"KK 窗口标题: {window_title}")
    logger.info(f"客户区目标尺寸: {main_size}")
    logger.info(f"搜索地图名: {map_name}")
    logger.info(f"验证关键词: {keyword}")

    # 解析测试矩阵
    mouse_modes = DEFAULT_MOUSE_MODES if args.mouse is None else args.mouse.split(",")
    keypad_modes = DEFAULT_KEYPAD_MODES if args.keypad is None else args.keypad.split(",")
    modes = DEFAULT_MODES if args.mode is None else [args.mode]
    cases = build_test_cases(mouse_modes, keypad_modes, modes, display=args.display)

    dm = create_dm_client()
    logger.info(f"大漠版本: {dm.version}")
    inf = get_inference_client(load_chest=False, load_combat=False)

    try:
        # 查找窗口并对齐尺寸
        hwnd = find_hall_window(dm, window_class, window_title)
        if not hwnd:
            logger.error("未找到 KK 主界面窗口")
            return 1
        logger.info(f"找到 KK 主界面窗口: hwnd={hwnd}")

        dm.set_client_size(hwnd, *main_size)
        time.sleep(0.5)

        OUT_DIR.mkdir(parents=True, exist_ok=True)

        results = []
        for i, case in enumerate(cases, 1):
            label = (
                f"input_{case['display']}_{case['mouse']}_{case['keypad']}_"
                f"mode{case['mode']}"
            )
            logger.info(f"\n[{i}/{len(cases)}] 测试组合: display={case['display']}, "
                        f"mouse={case['mouse']}, keypad={case['keypad']}, mode={case['mode']}")
            result = test_input_case(dm, hwnd, main_cfg, map_name, keyword, case, label, inf)
            results.append({"label": label, **result})

        # 汇总
        logger.info("\n" + "=" * 60)
        logger.info("测试结果汇总")
        logger.info("=" * 60)
        for r in results:
            status = "通过" if r["keyword_found"] else "失败"
            logger.info(
                f"{r['label']}: {status} | "
                f"bind={r['bind_ok']} input={r['input_ok']} search={r['search_ok']} "
                f"keyword_found={r['keyword_found']} | "
                f"screenshot={r.get('screenshot', '')}"
            )

        passed = sum(1 for r in results if r["keyword_found"])
        logger.info(f"\n总计 {len(results)} 种组合，{passed} 种搜索成功")
        return 0 if passed > 0 else 1

    finally:
        dm.close()


if __name__ == "__main__":
    sys.exit(main())
