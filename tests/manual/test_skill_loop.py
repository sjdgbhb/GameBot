"""技能按键循环测试 — 每个技能每 1 秒按一次（W / T / Q）。

用法（主环境 .venv）：
  .venv/Scripts/python.exe tests/manual/test_skill_loop.py

流程：
  1. 浮窗倒计时（按 Num- 可停止）
  2. 绑定 war3 窗口（不修改窗口尺寸，使用当前客户区坐标系）
  3. 循环：每个技能按各自 interval 到点施放，不做施放检测；
     同一技能持续连按，被控制吞掉的按键会在下一轮补回来；
     任意两次按键之间仅受 SKILL_GAP 后摇约束（撞车时按 SKILL_LIST 顺序放）

调试：每次按键带时间戳 print 到控制台。

注意：脚本不会调用 set_client_size 重置窗口尺寸；
坐标按当前窗口客户区坐标解释，窗口尺寸与录制坐标时不一致会导致落点偏移。
"""

import time

from GameBot.config import config
from GameBot.runner import create_dm_client
from GameBot.runner.ui import run_with_float_window

# ==================== 配置区 ====================

# 技能列表：每个技能到点按键施放。
#   key      — 技能按键
#   interval — 施放间隔（秒）
#   targeted — 是否指向性技能（True：按键后移动到 coords 左键点击确认）
#   coords   — 指向性技能的目标坐标 [x, y]（客户区坐标）；
#              字符串 "center" 表示客户区中心（按绑定时的实际客户区计算，
#              脚本不重置窗口尺寸）
SKILL_LIST = [
    {"key": "w", "interval": 1.0, "targeted": True, "coords": "center"},
    {"key": "t", "interval": 10.0, "targeted": False},
    {"key": "q", "interval": 3.0, "targeted": False},
]

# 任意两次按键之间的最小间隔（秒），等待前一个技能后摇结束
SKILL_GAP = 0.3

# 每次施放技能前是否先按 F1 选中英雄（防止左键误选其他单位后技能落空）
RESELECT_HERO = True

# 两次 F1 的最小间隔（秒）：war3 中短时间内连按两次 F1 会触发
# "镜头跳到英雄"，距上次 F1 不足该间隔时跳过本次重选
F1_MIN_INTERVAL = 0.6

# ==================== 逻辑区 ====================


def main():
    cfg = config.load_task("war3")
    war3_cfg = cfg.get("war3", {})

    def task_func(stop_event, progress_callback=None):
        dm = create_dm_client()

        hwnd = dm.get_active_window(
            war3_cfg.get("window_class", ""),
            war3_cfg.get("window_title", ""),
        )
        if not hwnd:
            progress_callback("未找到 war3 窗口，请先切换到魔兽窗口")
            return

        key_time = war3_cfg.get("key_time", 0.1)

        with dm.bind_window(hwnd):
            # 客户区中心坐标（coords="center" 时使用）
            cx1, cy1, cx2, cy2 = dm.get_client_rect(hwnd)
            client_center = [(cx2 - cx1) // 2, (cy2 - cy1) // 2]

            # 启动时按一次 F1 选中英雄
            if RESELECT_HERO:
                dm.key_press_char("F1")
                time.sleep(key_time)
            last_f1 = time.monotonic()

            start = time.monotonic()
            # 每个技能的调度状态：next=下一次按键时间
            state = {s["key"]: {"cfg": s, "next": start, "count": 0} for s in SKILL_LIST}
            next_cast_time = 0.0  # 任意下一次按键的最早时间（后摇保护）

            def cast(tag: str):
                """执行一次施放：F1 重选英雄（距上次 F1 不足 F1_MIN_INTERVAL 则跳过，
                防止被判定为双击 F1 跳镜头）→ 按键 → 指向性技能则移动并点击目标。"""
                nonlocal last_f1
                st = state[tag]
                skill = st["cfg"]
                st["count"] += 1
                print(f"[{time.strftime('%H:%M:%S')}] 第 {st['count']} 次按 {tag.upper()}")
                if RESELECT_HERO and time.monotonic() - last_f1 >= F1_MIN_INTERVAL:
                    dm.key_press_char("F1")
                    last_f1 = time.monotonic()
                    time.sleep(key_time)
                dm.key_press_char(tag)
                if skill["targeted"]:
                    time.sleep(key_time)
                    coords = client_center if skill["coords"] == "center" else skill["coords"]
                    dm.move_to(*coords)
                    time.sleep(key_time)
                    dm.left_click()

            while not stop_event.is_set():
                now = time.monotonic()

                if now < next_cast_time:
                    time.sleep(0.1)
                    continue

                # 找到第一个到点的技能；都无到点则等待
                tag = None
                for k, st in state.items():
                    if now >= st["next"]:
                        tag = k
                        break
                if tag is None:
                    time.sleep(0.1)
                    continue

                cast(tag)
                done = time.monotonic()
                # 后摇：此期间内不按任何技能
                next_cast_time = done + SKILL_GAP
                state[tag]["next"] = done + st["cfg"]["interval"]

            summary = "，".join(f"{k.upper()} 共 {v['count']} 次" for k, v in state.items())
            progress_callback(f"测试结束：{summary}")

    run_with_float_window("技能循环测试", task_func, countdown_seconds=5)


if __name__ == "__main__":
    main()
