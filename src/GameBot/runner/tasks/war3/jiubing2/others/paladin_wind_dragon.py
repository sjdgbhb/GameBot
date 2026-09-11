"""
圣骑士风龙挂机 — 图色检测技能图标，就绪即放。

不做按键计时：轮询各技能图标，图标与就绪态图片匹配（未变灰）即施放；
冷却中图标变灰不匹配则跳过。被控制/沉默吞掉的按键，待控制结束后
图标恢复就绪态，下一轮检测自然补上，无需额外重试逻辑。

技能格坐标由 skill_panel 配置（first_coords + gap）计算，依赖统一窗口尺寸。
配置见 tasks/others/paladin_wind_dragon.toml。
"""

from __future__ import annotations

import time

from GameBot.config import config
from GameBot.runner.business.war3 import War3Business
from GameBot.runner.business.war3.jiubing2 import GameUI
from GameBot.runner.driver import create_dm_client
from GameBot.runner.ui import run_with_float_window
from GameBot.utils import StopTaskError, logger, setup_global_exception_hook, setup_log_file


class PaladinWindDragonTask:
    """圣骑士风龙挂机 — 图色检测技能就绪即放。"""

    def __init__(
        self,
        cfg: dict,
        stop_event=None,
        progress_callback=None,
        progress_lines_callback=None,
        dm=None,
    ):
        self.task_cfg = cfg
        self.cfg = cfg["war3"]["jiubing2"]["tasks"]["others"]["paladin_wind_dragon"]
        self.dm = dm or create_dm_client()
        self._stop_event = stop_event
        self._progress_callback = progress_callback or (lambda text: None)
        self._progress_lines_callback = progress_lines_callback

        self.war3_cfg = cfg.get("war3", {})
        self.hero_cfg = cfg.get("hero", {})
        self.war3 = War3Business(self.dm, self.war3_cfg)
        self.ui = GameUI(self.dm, self.war3_cfg, self.hero_cfg, self.task_cfg, self.war3)

        self.skills = self.cfg.get("skills", [])
        self.skill_gap = self.cfg.get("skill_gap", 0.3)
        self.poll_interval = self.cfg.get("poll_interval", 0.2)
        # 施放确认窗口（秒）：按键到图标变灰存在延迟（含施法前摇），施放后必须观察到
        # 一次变灰才允许再次施放；超过该时长仍未变灰视为按键被吞（被控制/未生效），允许重按
        self.cast_confirm_time = self.cfg.get("cast_confirm_time", 2.0)
        self.f1_min_interval = self.cfg.get("f1_min_interval", 0.6)
        self.reselect_idle_time = self.cfg.get("reselect_idle_time", 5)
        self.icon_sim = self.cfg.get("icon_sim", 0.9)
        self.icon_delta_color = self.cfg.get("icon_delta_color", "202020")
        self.icon_search_half = self.cfg.get("icon_search_half", [40, 30])

        self._last_f1 = 0.0  # 上次按 F1 时刻（防双击跳镜头）
        self._last_cast = 0.0  # 上次施放成功时刻
        self._last_idle_f1 = 0.0  # 上次空闲 F1 重选时刻
        self._ready_state = {}  # key -> 最近一轮是否就绪（浮窗显示用）
        self._cast_counts = {}  # key -> 施放次数
        # key -> 施放后必须观察到图标变灰一次才允许再次施放（防变灰延迟导致重复按）
        self._need_cd_confirm = {}
        # key -> 确认截止时间，超时未变灰视为按键被吞，允许重按
        self._confirm_deadline = {}
        self.client_center = None  # 客户区中心（target_coords="center" 用）

    # ── 基础 ─────────────────────────────────────────────

    def _interruptible_wait(self, seconds: float):
        """可被停止信号中断的等待，检测到停止时抛出 StopTaskError。"""
        if self._stop_event is not None:
            if self._stop_event.wait(seconds):
                raise StopTaskError("用户请求停止任务")
        else:
            time.sleep(seconds)

    def _reselect_hero(self):
        """按 F1 重选英雄（施放前必调）；距上次 F1 不足 f1_min_interval 时等待补足，
        既保证每次施放前都选中英雄，又避免两次 F1 间隔过短被游戏判定为双击跳镜头。"""
        elapsed = time.monotonic() - self._last_f1
        if elapsed < self.f1_min_interval:
            self._interruptible_wait(self.f1_min_interval - elapsed)
        self.dm.key_press_char("F1")
        self._last_f1 = time.monotonic()
        # F1 与后续技能键之间用 general_time，间隔太短游戏可能丢键
        self._interruptible_wait(self.war3_cfg.get("general_time", 0.3))

    # ── 技能检测与施放 ────────────────────────────────────

    def _icon_area(self, skill: dict) -> list:
        """技能格中心的图标检测区域 [x1, y1, x2, y2]（客户区坐标）。"""
        cx, cy = self.ui.get_skill_coords(*skill["grid"])
        hw, hh = self.icon_search_half
        return [cx - hw, cy - hh, cx + hw, cy + hh]

    def _is_ready(self, skill: dict) -> bool:
        """图标与就绪态图片匹配 = 冷却完毕可施放；不匹配（变灰/扫层）= 冷却中。"""
        x1, y1, x2, y2 = self._icon_area(skill)
        index, _, _ = self.dm.find_pic(
            x1,
            y1,
            x2,
            y2,
            skill["image"],
            sim=self.icon_sim,
            delta_color=self.icon_delta_color,
        )
        return index != -1

    def _target_coords(self, skill: dict):
        """指向性技能目标坐标："center" 或缺省取客户区中心。"""
        coords = skill.get("target_coords")
        if coords == "center" or not coords:
            return self.client_center
        return coords

    def _cast(self, skill: dict):
        """施放一次技能。

        - self_cast：Alt+技能键 自我施放，完全不碰鼠标，免疫视角偏移（推荐用于
          可对自己/友军施放的指向性技能）
        - 其余：F1 重选英雄 → 按键 → 指向性技能则移动并点击目标
        """
        key_time = self.war3_cfg.get("key_time", 0.1)
        key = skill["key"]
        self_cast = skill.get("self_cast", False)
        targeted = skill.get("targeted") and not self_cast

        self._reselect_hero()

        if self_cast:
            # Alt+技能键 = war3 自我施放
            self.dm.key_down_char("alt")
            self._interruptible_wait(key_time)
            self.dm.key_press_char(key)
            self.dm.key_up_char("alt")
        else:
            self.dm.key_press_char(key)
            if targeted:
                self._interruptible_wait(key_time)
                self.dm.move_to(*self._target_coords(skill))
                self._interruptible_wait(key_time)
                self.dm.left_click()
        self._cast_counts[key] = self._cast_counts.get(key, 0) + 1
        self._last_cast = time.monotonic()
        # 进入施放确认：需观察到图标变灰一次才能再放，防止变灰延迟导致重复施放
        self._need_cd_confirm[key] = True
        self._confirm_deadline[key] = self._last_cast + self.cast_confirm_time
        logger.info(f"施放 {skill.get('name', key.upper())}（第 {self._cast_counts[key]} 次）")

    def _report_lines(self):
        """刷新浮窗多行状态：各技能施放次数。"""
        if not self._progress_lines_callback:
            return
        lines = [
            f"{skill.get('name', skill['key'].upper())}：{self._cast_counts.get(skill['key'], 0)} 次"
            for skill in self.skills
        ]
        self._progress_lines_callback(lines)

    # ── 检测测试 ────────────────────────────────────────

    def test_detect_icons(self):
        """检测测试：对每个技能格截图存 BMP + 多档相似度试匹配，用于排查图标匹配问题。

        截图输出到 logs/paladin_wind_dragon_detect/，日志打印各档 sim 的 find_pic 结果：
        - 截图中图标不在区域中央/区域不对 → grid 或 skill_panel 坐标有问题
        - 仅低 sim 匹配 → 截图与就绪态图片不一致（分辨率、灰度、扫层等）
        - 所有 sim 均不匹配 → 图片内容与屏幕完全不同
        """
        import tempfile
        from pathlib import Path

        out_dir = Path(tempfile.gettempdir()) / "paladin_wind_dragon_detect"
        out_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"检测测试模式：截图输出到 {out_dir}")

        for skill in self.skills:
            key = skill["key"]
            x1, y1, x2, y2 = self._icon_area(skill)
            logger.info(f"{skill.get('name', key.upper())} 检测区域 [{x1},{y1},{x2},{y2}]")

            # 截取当前技能格区域，便于人工核对坐标是否对准图标
            bmp = out_dir / f"icon_{key}.bmp"
            ok = self.dm.capture_region(x1, y1, x2, y2, str(bmp))
            logger.info(f"  区域截图 {'已保存 ' + str(bmp) if ok else '失败'}")

            # 多档相似度试匹配
            for sim in (0.9, 0.8, 0.7, 0.6, 0.5):
                index, px, py = self.dm.find_pic(
                    x1,
                    y1,
                    x2,
                    y2,
                    skill["image"],
                    sim=sim,
                    delta_color=self.icon_delta_color,
                )
                logger.info(f"  sim={sim} → index={index}" + (f" 命中于 ({px},{py})" if index != -1 else ""))

        logger.info("检测测试完成，请查看上述日志与截图")

    # ── 主流程 ──────────────────────────────────────────

    def run_core(self, hwnd):
        """核心挂机循环 — 假设窗口已绑定。供 run() 和组队步骤调用。"""
        self.war3.set_client_size(hwnd)
        x1, y1, x2, y2 = self.dm.get_client_rect(hwnd)
        self.client_center = [(x2 - x1) // 2, (y2 - y1) // 2]
        self._last_cast = time.monotonic()

        if self.cfg.get("is_test_detect", False):
            self.test_detect_icons()
            return

        skill_names = "、".join(f"{s['key'].upper()}{s.get('name', '')}" for s in self.skills)
        logger.info(f"圣骑士风龙挂机开始：技能 {skill_names}，客户区中心 {self.client_center}")

        while True:
            if self._stop_event is not None and self._stop_event.is_set():
                raise StopTaskError("用户请求停止任务")

            casted = False
            for skill in self.skills:
                if self._stop_event is not None and self._stop_event.is_set():
                    raise StopTaskError("用户请求停止任务")
                ready = self._is_ready(skill)
                key = skill["key"]
                self._ready_state[key] = ready

                if self._need_cd_confirm.get(key):
                    if not ready:
                        # 图标已变灰，确认技能真实放出进入 CD
                        self._need_cd_confirm.pop(key)
                        continue
                    if time.monotonic() < self._confirm_deadline.get(key, 0):
                        # 确认窗口内图标仍未变灰：变灰延迟中，跳过不重复按
                        continue
                    # 超时仍未变灰 → 按键被吞（被控制/未生效），解除确认允许重按
                    self._need_cd_confirm.pop(key)
                    logger.warning(f"{skill.get('name', key.upper())} 按键疑似被吞（未观察到变灰），重新施放")

                if ready:
                    self._cast(skill)
                    casted = True
                    # 后摇：两次施放之间的最小间隔
                    self._interruptible_wait(self.skill_gap)

            self._report_lines()

            if not casted:
                # 长时间无任何技能就绪，可能英雄选中丢失，按一次 F1 兜底
                now = time.monotonic()
                if (
                    self.reselect_idle_time > 0
                    and now - self._last_cast >= self.reselect_idle_time
                    and now - self._last_idle_f1 >= self.reselect_idle_time
                ):
                    self._reselect_hero()
                    self._last_idle_f1 = now
                self._interruptible_wait(self.poll_interval)

    def _bind_cfg(self) -> dict:
        """绑定参数（load_task 已按 bind_mode 解析好写入 war3.bind）。"""
        bind_cfg = self.war3_cfg.get("bind", {})
        if bind_cfg.get("bind_mode") == "background":
            logger.info(f"使用后台绑定: {bind_cfg}")
        return bind_cfg

    def _find_war3_hwnd(self) -> int:
        """查找 war3 窗口。后台模式不要求 war3 是活动窗口，直接按类名+标题找。"""
        if self.war3_cfg.get("bind", {}).get("bind_mode") == "background":
            return self.dm.find_window(self.war3_cfg["window_class"], self.war3_cfg["window_title"]) or 0
        return self.dm.get_active_window(self.war3_cfg["window_class"], self.war3_cfg["window_title"])

    def run(self):
        """主入口 — 查找窗口、绑定、统一窗口尺寸、运行挂机循环。"""
        if not self.skills:
            logger.error("未配置技能列表（this.skills）")
            return

        hwnd = self._find_war3_hwnd()
        if not hwnd:
            logger.error("未找到 war3 窗口")
            return

        with self.dm.bind_window(hwnd, bind_cfg=self._bind_cfg()):
            self.run_core(hwnd)

        summary = "，".join(f"{k.upper()} {v} 次" for k, v in self._cast_counts.items())
        logger.info(f"圣骑士风龙挂机结束：{summary or '无施放'}")


def main():
    setup_global_exception_hook()
    setup_log_file("圣骑士风龙")
    logger.info("############################# 圣骑士风龙挂机 #############################")
    cfg = config.load_task("war3.jiubing2.tasks.others.paladin_wind_dragon")

    def task_wrapper(stop_event, progress_callback=None, **kwargs):
        PaladinWindDragonTask(
            cfg,
            stop_event=stop_event,
            progress_callback=progress_callback,
            progress_lines_callback=kwargs.get("progress_lines_callback"),
        ).run()

    run_with_float_window("圣骑士风龙", task_wrapper, countdown_seconds=5, float_cfg=cfg.get("float_window", {}))


if __name__ == "__main__":
    main()


# ── 组队任务步骤 ────────────────────────────────────────────


from GameBot.runner.business.war3.jiubing2.team_steps_base import Jiubing2TaskSteps


class _PaladinWindDragonSteps(Jiubing2TaskSteps):
    """风龙挂机组队步骤 — preparation 继承九兵通用流程，run_task 执行挂机循环。"""

    def run_task(self, member, stop_event=None, **kwargs):
        """挂机主循环（窗口已由 _game_phase 绑定，直接使用 member.dm）。"""
        task = PaladinWindDragonTask(member.task_cfg, stop_event=stop_event, dm=member.dm)
        hwnd = member._current_war3_hwnd
        if not hwnd:
            logger.error("run_task 无可用 War3 窗口句柄")
            member._flow_failed = True
            return
        try:
            task.run_core(hwnd)
        except StopTaskError:
            logger.info("用户请求停止风龙挂机")
            raise
        except Exception as e:
            logger.error(f"风龙挂机任务异常: {e}")
            member._flow_failed = True


_steps = _PaladinWindDragonSteps()
preparation = _steps.preparation
position_init = _steps.position_init
pre_exit = _steps.pre_exit
run_task = _steps.run_task
