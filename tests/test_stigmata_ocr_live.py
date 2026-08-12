"""圣痕面板 OCR 实测脚本 — 在游戏中按 F2 打开圣痕面板，OCR 读取并打印结果。

用法（大漠脚本环境 .venv-dm）：
  .venv-dm/Scripts/python.exe tests/test_stigmata_ocr_live.py

流程：
  1. 浮窗倒计时（与正式任务一致，按 Num- 可停止）
  2. 绑定 war3 窗口
  3. 按 F2 打开圣痕面板
  4. OCR 读取 num_coords 区域
  5. 打印原始 OCR 行、合并全文、解析结果
  6. 按 F2 关闭面板
"""
import time

from GameBot.config import config
from GameBot.inference import get_ocr_client
from GameBot.runner.dm_client import DmClient
from GameBot.runner.tasks.war3.jiubing2.others.upgrade_stigmata import UpgradeStigmataTask
from GameBot.runner.ui import run_with_float_window
from GameBot.utils import logger


def main():
    cfg = config.load_task("war3.jiubing2.tasks.others.upgrade_stigmata")
    stigmata_cfg = cfg.get("stigmata", {})
    war3_cfg = cfg.get("war3", {})
    num_coords = stigmata_cfg.get("num_coords")
    hotkey = stigmata_cfg.get("switch_hotkey", "F2")
    term_limit = stigmata_cfg.get("term_limit", {})

    if not num_coords:
        logger.error("未配置 stigmata.num_coords")
        return

    logger.info(f"圣痕配置: num_coords={num_coords}, hotkey={hotkey}")

    def task_func(stop_event, progress_callback=None):
        progress_callback("绑定窗口...")
        dm = DmClient()
        hwnd = dm.get_active_window(
            war3_cfg.get("window_class", ""),
            war3_cfg.get("window_title", ""),
        )
        if not hwnd:
            progress_callback("未找到 war3 窗口")
            return

        get_ocr_client()  # 预热 OCR 子进程

        # 客户区坐标转屏幕坐标
        cx, cy, _, _ = dm.get_client_rect(hwnd)
        screen_bbox = [cx + num_coords[0], cy + num_coords[1],
                       cx + num_coords[2], cy + num_coords[3]]
        print(f"客户区坐标: {num_coords}")
        print(f"窗口原点: ({cx}, {cy})")
        print(f"屏幕坐标: {screen_bbox}")

        with dm.bind_window(hwnd):
            # 先打开圣痕面板
            progress_callback(f"按 {hotkey} 打开圣痕面板...")
            dm.key_press_char(hotkey)
            time.sleep(war3_cfg.get("small_window_response_time", 0.5))

            # 框选 OCR 区域（用客户区坐标），暂停 3 秒供肉眼核对
            x1, y1, x2, y2 = num_coords
            dm.move_to(x1, y1)
            time.sleep(0.1)
            dm.left_down()
            time.sleep(0.1)
            dm.move_to(x2, y2)
            progress_callback(f"框选 OCR 区域 {num_coords}，3s 后继续")
            time.sleep(3)
            dm.left_up()

            progress_callback("OCR 读取中...")
            client = get_ocr_client()

            # 整体 OCR（用屏幕坐标）
            lines = client.ocr_lines(screen_bbox)

            # 行数不足 4 时，按 4 等分逐行单独 OCR
            if len(lines) < 4:
                x1, y1, x2, y2 = screen_bbox
                row_h = (y2 - y1) // 4
                print(f"\n--- 逐行 OCR (每行高 {row_h}px) ---")
                row_lines = []
                for row_idx in range(4):
                    ry1 = y1 + row_idx * row_h
                    ry2 = y1 + (row_idx + 1) * row_h if row_idx < 3 else y2
                    row_bbox = [x1, ry1, x2, ry2]
                    r_lines = client.ocr_lines(row_bbox)
                    # y 坐标加上行偏移
                    for line in r_lines:
                        line["y_center"] = line.get("y_center", 0) + (ry1 - y1)
                    pos_name = ["upper", "core", "middle", "lower"][row_idx]
                    print(f"  [{pos_name}] bbox={row_bbox}")
                    for i, line in enumerate(r_lines):
                        print(f"    [{i}] y={line.get('y_center', '?'):>6}  text={line.get('text', '')!r}")
                    row_lines.extend(r_lines)

                # 合并去重
                all_lines = list(lines)
                for rl in row_lines:
                    if not any(abs(rl.get("y_center", 0) - el.get("y_center", 0)) < 20
                               for el in all_lines):
                        all_lines.append(rl)
                all_lines.sort(key=lambda l: l.get("y_center", 0))
                lines = all_lines

            dm.key_press_char(hotkey)
            time.sleep(war3_cfg.get("general_time", 0.3))

        # 打印结果
        print("\n" + "=" * 60)
        print("OCR 原始行（含 y 坐标）:")
        print("=" * 60)
        for i, line in enumerate(lines):
            print(f"  [{i}] y={line.get('y_center', '?'):>6}  text={line.get('text', '')!r}")

        full_text = "\n".join(line.get("text", "") for line in lines)
        print("\n" + "=" * 60)
        print(f"合并全文: {full_text!r}")
        print("=" * 60)

        result = UpgradeStigmataTask._parse_stigmata_text(full_text, term_limit)
        print("\n" + "=" * 60)
        print("解析结果:")
        print("=" * 60)
        for pos in ("upper", "core", "middle", "lower"):
            terms = result.get(pos, [])
            if terms:
                terms_str = "  ".join(f"{name}={val}" for name, val in terms)
                print(f"  {pos:6s}: {terms_str}")
            else:
                print(f"  {pos:6s}: (未识别)")

        print("\n" + "=" * 60)
        print("未达上限词条:")
        print("=" * 60)
        target = UpgradeStigmataTask._pick_upgrade_target(result, term_limit)
        if target is None:
            print("  全部达上限（或无数据）")
        else:
            pos, idx, name, current, limit = target
            print(f"  优先升级: {pos} 词条{idx} {name} 当前={current}/{limit} 差距={limit - current}")

        progress_callback("完成")
        print("\n完成。")

    run_with_float_window("圣痕OCR测试", task_func, countdown_seconds=5)


if __name__ == "__main__":
    main()
