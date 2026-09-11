"""钓鱼找色测试 — 框选检测区域 + 找到红色时框选命中点，肉眼核对找色是否正常。

用法（主环境（uv run））：
  uv run python tests/manual/test_fishing_color.py

流程：
  1. 浮窗倒计时（按 Num- 可停止）
  2. 绑定 war3 窗口，强制设置客户区尺寸（重置窗口）
  3. 先框选完整检测区域一次，供肉眼确认区域位置
  4. 循环：抛竿 → 高频找色等待中钩 → 找到红色时框选命中点 → 收竿
  5. 按 Num- 停止
"""

import time

from GameBot.config import config
from GameBot.runner.business.war3 import War3Business
from GameBot.runner.business.war3.jiubing2 import get_inventory_hotkey
from GameBot.runner.driver import create_dm_client
from GameBot.runner.ui import run_with_float_window

# 命中点框选半径（像素），框选以命中坐标为中心的正方形区域
HIT_BOX_RADIUS = 30
# 命中后框选停留时间（秒），供观察
HOLD_TIME = 3
# 找色轮询间隔（秒），抛竿后高频检测中钩
POLL_INTERVAL = 0.005
# 首次框选完整检测区域的停留时间（秒）
AREA_HOLD_TIME = 5
# 等待中钩超时时间（秒）
HOOK_TIMEOUT = 15
# 两次抛竿间隔（秒）
FISHING_INTERVAL = 1


def _box_select(dm, coords, hold_time, stop_event):
    """框选区域 [x1, y1, x2, y2]，停留 hold_time 秒供观察。"""
    dm.move_to(*coords[:2])
    time.sleep(0.1)
    dm.left_down()
    time.sleep(0.1)
    dm.move_to(*coords[2:])
    elapsed = 0.0
    while elapsed < hold_time and not stop_event.is_set():
        time.sleep(0.1)
        elapsed += 0.1
    dm.left_up()


def main():
    cfg = config.load_task("war3.jiubing2.tasks.others.fishing")
    war3_cfg = cfg.get("war3", {})
    fishing_cfg = cfg.get("war3", {}).get("jiubing2", {}).get("tasks", {}).get("others", {}).get("fishing", {})
    check_cfg = fishing_cfg.get("check", {})

    x1, y1, x2, y2 = check_cfg["status_area_coords"]
    hook_color = check_cfg.get("hook_color", "ff0000")
    delta_color = check_cfg.get("hook_delta_color", "000000")
    color_str = f"{hook_color}-{delta_color}"
    sim = check_cfg["hook_sim"]
    mode = fishing_cfg.get("mode", 0)

    print(f"检测模式: {'找图+找色' if mode != 0 else '纯找色'} (mode={mode})")
    print(f"检测区域: [{x1}, {y1}, {x2}, {y2}]")
    print(f"找色颜色: {color_str}, 相似度: {sim}")
    print()

    hero_cfg = cfg.get("hero", {})
    hook_coords = fishing_cfg["hook_coords"]
    fishing_hotkey = get_inventory_hotkey(hero_cfg, 7)
    dm = None

    def _cast_rod():
        """抛竿：双击 F1 重置视角 → 移动到鱼钩位置 → 按快捷键 → 左键点击。"""
        dm.key_press_char("f1")
        time.sleep(0.05)
        dm.key_press_char("f1")
        time.sleep(0.1)
        dm.move_to(*hook_coords)
        time.sleep(0.1)
        dm.key_press_char(fishing_hotkey)
        time.sleep(0.1)
        dm.left_click()
        time.sleep(0.05)

    def _find_hook():
        """单次中钩检测，返回 (found, x, y)。mode=0 找色，mode=1 先找图再找色兜底。"""
        if mode != 0:
            img = check_cfg.get("hook_status_image", "")
            index, px, py = dm.find_pic(x1, y1, x2, y2, img, sim=sim, delta_color=delta_color)
            if index != -1:
                return True, px, py
        dm_ret, px, py = dm.find_color(x1, y1, x2, y2, color_str, sim)
        return dm_ret != 0, px, py

    def task_func(stop_event, progress_callback=None):
        nonlocal dm
        dm = create_dm_client()
        war3 = War3Business(dm, war3_cfg)

        hwnd = dm.get_active_window(
            war3_cfg.get("window_class", ""),
            war3_cfg.get("window_title", ""),
        )
        if not hwnd:
            progress_callback("未找到 war3 窗口，请先切换到魔兽窗口")
            return

        with dm.bind_window(hwnd):
            # 重置窗口尺寸
            progress_callback("重置窗口尺寸...")
            war3.set_client_size(hwnd)
            cx1, cy1, cx2, cy2 = dm.get_client_rect(hwnd)
            actual_w, actual_h = cx2 - cx1, cy2 - cy1
            expected = war3_cfg.get("client_size", [1902, 1033])
            print(f"窗口客户区: ({cx1}, {cy1}) ~ ({cx2}, {cy2}), 尺寸 {actual_w}x{actual_h}")
            if actual_w != expected[0] or actual_h != expected[1]:
                print("⚠ 客户区尺寸不匹配！坐标可能偏移")
                progress_callback(f"⚠ 尺寸不匹配: {actual_w}x{actual_h} vs {expected[0]}x{expected[1]}")
            else:
                print("✓ 客户区尺寸匹配")
                progress_callback(f"✓ 尺寸匹配 {actual_w}x{actual_h}")
            print()

            # 先框选完整检测区域
            progress_callback(f"框选检测区域 [{x1},{y1},{x2},{y2}]")
            print(f"框选检测区域 [{x1},{y1},{x2},{y2}]，停留 {AREA_HOLD_TIME}s")
            _box_select(dm, [x1, y1, x2, y2], AREA_HOLD_TIME, stop_event)

            if stop_event.is_set():
                progress_callback("测试结束")
                return

            # 循环：抛竿 → 等待中钩 → 框选命中点 → 收竿
            round_num = 0
            found_count = 0
            while not stop_event.is_set():
                round_num += 1
                progress_callback(f"第 {round_num} 轮: 抛竿")
                print(f"\n=== 第 {round_num} 轮: 抛竿 ===")
                _cast_rod()

                # 高频找色等待中钩
                start = time.perf_counter()
                found = False
                while time.perf_counter() - start < HOOK_TIMEOUT and not stop_event.is_set():
                    hit, px, py = _find_hook()
                    if hit:
                        found = True
                        break
                    time.sleep(POLL_INTERVAL)

                if found:
                    actual_color = dm.get_color(px, py)
                    elapsed = time.perf_counter() - start
                    progress_callback(f"第 {round_num} 轮: 中钩! ({px},{py}) 颜色={actual_color} 耗时={elapsed:.1f}s")
                    print(
                        f"[第 {round_num} 轮] 找色命中: 坐标=({px},{py}), 实际颜色={actual_color}, "
                        f"查找颜色={color_str}, sim={sim}, 耗时={elapsed:.2f}s"
                    )
                    # 框选命中点
                    hit_box = [px - HIT_BOX_RADIUS, py - HIT_BOX_RADIUS, px + HIT_BOX_RADIUS, py + HIT_BOX_RADIUS]
                    _box_select(dm, hit_box, HOLD_TIME, stop_event)
                    found_count += 1
                    # 收竿
                    dm.key_press_char("s")
                    print(f"[第 {round_num} 轮] 已按 S 收竿")
                else:
                    progress_callback(f"第 {round_num} 轮: 超时未中钩")
                    print(f"[第 {round_num} 轮] {HOOK_TIMEOUT}s 内未找到红色")
                    # 框选完整检测区域供观察
                    _box_select(dm, [x1, y1, x2, y2], HOLD_TIME, stop_event)

                if stop_event.is_set():
                    break

                # 两次抛竿间隔
                elapsed = 0.0
                while elapsed < FISHING_INTERVAL and not stop_event.is_set():
                    time.sleep(0.1)
                    elapsed += 0.1

            print(f"\n测试结束：共抛竿 {round_num} 次，中钩 {found_count} 次")
            progress_callback("测试结束")

    run_with_float_window("钓鱼找色测试", task_func, countdown_seconds=5)


if __name__ == "__main__":
    main()
