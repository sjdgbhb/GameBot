"""
钓鱼任务
"""

import time
from typing import TYPE_CHECKING, Optional

from GameBot.config import config as config
from GameBot.runner.business.war3 import War3Business
from GameBot.runner.business.war3.jiubing2 import NearbyCleaner, get_inventory_hotkey
from GameBot.runner.driver import create_dm_client
from GameBot.runner.ui import run_with_float_window
from GameBot.utils import StopTaskError, logger, setup_global_exception_hook, setup_log_file

if TYPE_CHECKING:
    from GameBot.runner.driver.base import DmClientBase


class FishingTask:
    __doc__ = "钓鱼业务"

    def __init__(self, cfg: dict, stop_event=None, progress_callback=None, dm: Optional["DmClientBase"] = None):
        self.task_cfg = cfg
        self.dm: "DmClientBase" = dm or create_dm_client()
        self._stop_event = stop_event
        self._progress_callback = progress_callback or (lambda text: None)
        self.war3_cfg = cfg.get("war3", {})
        self.war3 = War3Business(self.dm, self.war3_cfg)
        self.fishing_cfg = cfg.get("war3", {}).get("jiubing2", {}).get("tasks", {}).get("others", {}).get("fishing", {})
        self.check_cfg = self.fishing_cfg.get("check", {})
        self.prompt_cfg = cfg.get("prompt_text", {})
        self.hero_cfg = cfg.get("hero", {})
        self.fishing_hotkey = get_inventory_hotkey(self.hero_cfg, 7)
        self._last_success_text = ""
        self._ocr_bbox = self.prompt_cfg.get("last_area_coords")
        self._success_count = 0
        self._hook_no_success_count = 0
        self._fill_period = None
        clear_nearby_probability = self.fishing_cfg.get("clear_nearby_probability", 0)
        self.nearby_cleaner = (
            NearbyCleaner(
                self.war3,
                cfg.get("command", {}),
                probability=clear_nearby_probability,
            )
            if clear_nearby_probability > 0
            else None
        )

    def _interruptible_wait(self, seconds: float):
        """可被停止信号中断的等待，检测到停止时抛出 StopTaskError。"""
        if self._stop_event is not None:
            if self._stop_event.wait(seconds):
                raise StopTaskError("用户请求停止任务")
        else:
            time.sleep(seconds)

    def test_check_area(self, duration=5):
        """抛竿后测试中钩检测区域：截图 + 检测 + 框选区域。"""
        logger.info("测试模式：先抛竿再检测中钩区域")
        self._cast_rod()
        self._interruptible_wait(1)
        x1, y1, x2, y2 = self.check_cfg["status_area_coords"]
        detect_mode = self.fishing_cfg.get("mode", 0)
        if detect_mode != 0:
            delta_color = self.check_cfg.get("hook_delta_color", "000000")
            sim = self.check_cfg["hook_sim"]
            img = self.check_cfg.get("hook_status_image", "")
            index, px, py = self.dm.find_pic(x1, y1, x2, y2, img, sim=sim, delta_color=delta_color)
            if index != -1:
                logger.warning(f"抛竿后 find_pic 匹配到图片！index={index}, 坐标=({px},{py}), 图片={img}, sim={sim}")
            else:
                logger.info(f"抛竿后 find_pic 未匹配（未中钩状态正常），图片={img}, sim={sim}")
        else:
            hook_color = self.check_cfg.get("hook_color", "ff0000")
            delta_color = self.check_cfg.get("hook_delta_color", "000000")
            color_str = f"{hook_color}-{delta_color}"
            sim = self.check_cfg["hook_sim"]
            dm_ret, px, py = self.dm.find_color(x1, y1, x2, y2, color_str, sim)
            if dm_ret != 0:
                logger.warning(f"抛竿后 find_color 匹配到颜色！坐标=({px},{py}), 颜色={color_str}, sim={sim}")
            else:
                logger.info(f"抛竿后 find_color 未匹配（未中钩状态正常），颜色={color_str}, sim={sim}")
        self.dm.move_to(x1, y1)
        self._interruptible_wait(0.1)
        self.dm.left_down()
        self._interruptible_wait(0.1)
        self.dm.move_to(x2, y2)
        logger.info(f"框选检测区域 [{x1},{y1},{x2},{y2}]，{duration}s 后继续")
        self._interruptible_wait(duration)
        self.dm.left_up()

    def _cast_rod(self):
        # 双击 F1 以英雄为中心重置游戏窗口视角
        logger.info(f"抛竿：F1×2 → 移动到 {self.fishing_cfg['hook_coords']} → 按键 {self.fishing_hotkey} → 左键点击")
        self.dm.key_press_char("f1")
        self._interruptible_wait(0.05)
        self.dm.key_press_char("f1")
        self._interruptible_wait(0.1)
        # 鼠标移动到鱼钩位置，使用快捷键钓鱼
        (self.dm.move_to)(*self.fishing_cfg["hook_coords"])
        self._interruptible_wait(0.1)
        self.dm.key_press_char(self.fishing_hotkey)
        self._interruptible_wait(0.1)
        self.dm.left_click()
        self._interruptible_wait(0.05)

    _hook_check_logged = False

    def _check_hook(self) -> bool:
        """检测中钩（收竿时机）。mode=0 找色，mode=1 先找图再找色。"""
        delta_color = self.check_cfg.get("hook_delta_color", "000000")
        hook_color = self.check_cfg.get("hook_color", "ff0000")
        color_str = f"{hook_color}-{delta_color}"
        sim = self.check_cfg["hook_sim"]
        x1, y1, x2, y2 = self.check_cfg["status_area_coords"]
        if self.fishing_cfg["mode"] != 0:
            # 找图模式：先找图，未命中再找色兜底
            index, x, y = self.dm.find_pic(
                x1, y1, x2, y2, (self.check_cfg["hook_status_image"]), sim=sim, delta_color=delta_color
            )
            found = index != -1
            if found:
                if not self._hook_check_logged:
                    self._hook_check_logged = True
                    logger.info(
                        f"找图首次命中：index={index}, 坐标=({x},{y}), 图片={self.check_cfg['hook_status_image']}, 区域=[{x1},{y1},{x2},{y2}]"
                    )
                return found
        # 找色模式（mode=0 直接找色，mode=1 找图未命中时兜底找色）
        dm_ret, x, y = self.dm.find_color(x1, y1, x2, y2, color_str, sim)
        found = dm_ret != 0
        if found:
            if not self._hook_check_logged:
                self._hook_check_logged = True
                logger.info(f"找色首次命中：坐标=({x},{y}), 颜色={color_str}, 区域=[{x1},{y1},{x2},{y2}]")
        return found

    def _wait_and_retract(self) -> bool:
        """等待中钩并预判收竿。返回是否已按下收竿键。

        填充循环往复且周期稳定（实测 ~3.1s，波动 ±25ms），
        而按键到游戏实际执行收竿存在 100~200ms 固有延迟，见红即收必然晚 1~2 格。
        因此用红色出现时刻加循环周期推算下次出现时刻，提前 retract_lead_time
        秒按键把延迟精确补偿掉。周期跨竿缓存：首竿等 2 次红色出现实测周期，
        后续竿只等 1 次即可出手。
        """
        timeout = self.check_cfg.get("hook_timeout", 15)
        interval = self.check_cfg.get("hook_check_interval", 0.005)
        lead = self.check_cfg.get("retract_lead_time", 0.1)
        t1 = self._wait_red_state(True, timeout)
        if t1 is None:
            return False
        if self._wait_red_state(False, timeout) is None:
            return False
        base = t1
        period = self._fill_period
        if period is None:
            t2 = self._wait_red_state(True, timeout)
            if t2 is None:
                return False
            period = t2 - t1
            self._fill_period = period
            logger.debug(f"实测填充循环周期 {period * 1000:.0f}ms（已缓存，后续竿只等 1 次红色出现）")
            if self._wait_red_state(False, timeout) is None:
                return False
            base = t2
        target = base + period - lead
        early = False
        while True:
            if self._stop_event is not None and self._stop_event.is_set():
                return False
            remaining = target - time.perf_counter()
            if remaining <= 0:
                break
            elif remaining > 0.05:
                if self._check_hook():
                    early = True
                    break
                time.sleep(min(interval, remaining - 0.05))
            else:
                time.sleep(remaining)

        self.dm.key_press_char("s")
        logger.debug(
            f"预判收竿：周期 {period * 1000:.0f}ms，提前 {lead * 1000:.0f}ms"
            + ("（红色提前出现，已兜底立即收竿）" if early else "")
        )
        return True

    def _wait_red_state(self, target: bool, timeout: float):
        """等待红色三角形填充处于目标状态（连续 2 次一致防抖），返回确认时刻，超时返回 None。"""
        interval = self.check_cfg.get("hook_check_interval", 0.005)
        start = time.perf_counter()
        consecutive = 0
        while time.perf_counter() - start < timeout:
            if self._stop_event is not None:
                if self._stop_event.is_set():
                    return
                if self._check_hook() == target:
                    consecutive += 1
                    if consecutive >= 2:
                        return time.perf_counter()
                else:
                    consecutive = 0
                time.sleep(interval)

        logger.warning(f"等待红色{'出现' if target else '消失'}超时（{timeout}s）— 请检查检测区域坐标和图片是否匹配")

    def run_fishing_loop(self):
        """钓鱼主循环（不绑定窗口，需调用方已绑定）。"""
        logger.info("开始钓鱼")
        if self.fishing_cfg.get("is_test_check", False):
            self.test_check_area()
            return

        max_times = self.fishing_cfg.get("max_times", 10000)
        interval = self.fishing_cfg.get("fishing_interval_time", 1)

        for i in range(max_times):
            if self._stop_event is not None and self._stop_event.is_set():
                raise StopTaskError("用户请求停止任务")

            logger.info(f"抛竿 {i + 1}/{max_times}")
            self._progress_callback(f"抛竿 {i + 1}/{max_times}")
            self._cast_rod()

            hooked = self._wait_and_retract()
            if not hooked:
                self._hook_no_success_count += 1
                logger.warning(f"未检测到中钩，连续 {self._hook_no_success_count} 次未成功")
            else:
                self._hook_no_success_count = 0

            # 清理附近物品
            if self.nearby_cleaner is not None:
                self.nearby_cleaner.tick()

            self._interruptible_wait(interval)

        logger.info(f"钓鱼结束，共抛竿 {max_times} 次")

    def run(self):
        """钓鱼主入口 — 查找窗口、绑定、运行钓鱼循环。"""
        hwnd = self.dm.get_active_window(self.war3_cfg["window_class"], self.war3_cfg["window_title"])
        if not hwnd:
            logger.error("未找到 war3 窗口")
            return

        with self.dm.bind_window(hwnd, bind_cfg=self.war3_cfg.get("bind", {})):
            self.war3.set_client_size(hwnd)
            self.run_fishing_loop()


def main():
    setup_global_exception_hook()
    setup_log_file("钓鱼")
    logger.info("############################# 钓鱼任务 #############################")
    cfg = config.load_task("war3.jiubing2.tasks.others.fishing")

    def task_wrapper(stop_event, progress_callback):
        FishingTask(cfg, stop_event=stop_event, progress_callback=progress_callback).run()

    run_with_float_window("钓鱼", task_wrapper, countdown_seconds=5, float_cfg=(cfg.get("float_window", {})))


if __name__ == "__main__":
    main()


# ── 组队任务步骤 ────────────────────────────────────────────


from GameBot.runner.business.war3.jiubing2.team_steps_base import Jiubing2TaskSteps


class _FishingSteps(Jiubing2TaskSteps):
    """钓鱼组队步骤 — preparation 继承九兵通用流程，run_task 执行钓鱼循环。"""

    def run_task(self, member, stop_event=None, **kwargs):
        """钓鱼主循环（窗口已由 _game_phase 绑定，直接使用 member.dm）。"""
        fishing_task = FishingTask(
            member.task_cfg,
            stop_event=stop_event,
            progress_callback=member.task_ctx._progress_callback,
            dm=member.dm,
        )
        fishing_task.run_fishing_loop()


_steps = _FishingSteps()
preparation = _steps.preparation
position_init = _steps.position_init
pre_exit = _steps.pre_exit
run_task = _steps.run_task
