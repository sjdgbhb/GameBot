"""
风龙挂机 — 图色检测技能图标，就绪即放。

与圣骑士风龙同套挂机逻辑，但不做走位/开 boss 等操作：
进入挂机循环后只轮询施放技能 + 定时喂宠物。

不做按键计时：轮询各技能图标，图标与就绪态图片匹配（未变灰）即施放；
冷却中图标变灰不匹配则跳过。被控制/沉默吞掉的按键，待控制结束后
图标恢复就绪态，下一轮检测自然补上，无需额外重试逻辑。

技能格坐标由 skill_panel 配置（first_coords + gap）计算，依赖统一窗口尺寸。
配置见 tasks/wind_dragon/wind_dragon.toml。
"""

from __future__ import annotations

import sys
import time

from GameBot.config import config, get_task_view, resolve_bind_cfg
from GameBot.runner.business.war3 import War3Business
from GameBot.runner.business.war3.jiubing2 import CombatHelper, GameUI, get_inventory_hotkeys
from GameBot.runner.driver import create_dm_client
from GameBot.runner.ui import run_with_float_window
from GameBot.utils import StopTaskError, logger, setup_global_exception_hook, setup_log_file


class WindDragonTask:
    """风龙挂机 — 图色检测技能就绪即放，定时喂宠物。"""

    def __init__(
        self,
        cfg: dict,
        task_name: str = "war3.jiubing2.tasks.wind_dragon.wind_dragon",
        stop_event=None,
        progress_callback=None,
        progress_lines_callback=None,
        dm=None,
    ):
        self.task_cfg = cfg
        # 任务视图：沿 extends 链深合并，变体不写的参数自动从基任务继承
        self.cfg = get_task_view(cfg, task_name)
        self.dm = dm or create_dm_client()
        self._stop_event = stop_event
        self._progress_callback = progress_callback or (lambda text: None)
        self._progress_lines_callback = progress_lines_callback

        self.war3_cfg = cfg.get("war3", {})
        self.hero_cfg = cfg.get("hero", {})
        self.war3 = War3Business(self.dm, self.war3_cfg)
        # target_player 在变体 [this] 里配置，注入 war3 做多开窗口认领
        self.war3.target_player = self.cfg.get("target_player", "")
        self.ui = GameUI(self.dm, self.war3_cfg, self.hero_cfg, self.task_cfg, self.war3)
        self.combat = CombatHelper(self.dm, self.war3_cfg, self.hero_cfg, self.task_cfg, self.war3)

        self.skills = self._resolve_skills()
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
        # "喂宠物的时间是否到了"的检测间隔（秒），0 表示关闭；实际喂食间隔
        # 由 jiubing2.toml [pet].feeding_interval（分钟）控制
        self.pet_feed_interval = self.cfg.get("pet_feed_interval", 0)
        self.pet_feed_time = time.time()
        self._feed_count = 0

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

    def _resolve_skills(self) -> list:
        """任务技能列表与英雄技能池合并：this.skills 按 skill（技能名，对应 hero.skills
        的 desc）引用，key/name/image/targeted 自动带出，任务侧只需写 grid、
        target_coords 等差异项；旧格式的数值 id 仍兼容。"""
        pool = self.hero_cfg.get("skills", [])
        by_name = {s.get("desc"): s for s in pool if s.get("desc")}
        by_id = {s.get("id"): s for s in pool if s.get("id") is not None}
        skills = []
        for s in self.cfg.get("skills", []):
            base = by_name.get(s.get("skill"), {})
            if not base and s.get("id") is not None:
                base = by_id.get(s["id"], {})  # 兼容旧数值 id 引用
            if not base and not (s.get("key") and s.get("image") and s.get("grid")):
                logger.warning(f'技能 "{s.get("skill") or s.get("id")}" 未在英雄技能池中找到，且缺少 key/image/grid，跳过')
                continue
            merged = {**base, **s}
            merged["key"] = str(merged.get("key", "")).lower()
            merged["name"] = merged.get("name") or merged.get("desc") or merged["key"].upper()
            merged["targeted"] = merged.get("targeted", merged.get("target_type", "self") != "self")
            skills.append(merged)
        no_image = [s["name"] for s in skills if not s.get("image")]
        if no_image:
            logger.warning(f"以下技能缺少就绪态图标 image，无法检测将永远不就绪：{no_image}")
        return skills

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
        image = skill.get("image")
        if not image:
            return False  # 未配置就绪态图标（启动时已告警），视为永不就绪
        x1, y1, x2, y2 = self._icon_area(skill)
        index, _, _ = self.dm.find_pic(
            x1,
            y1,
            x2,
            y2,
            image,
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

    def _feed_pet(self):
        """喂宠物（实际间隔由 jiubing2.toml [pet].feeding_interval 控制）。

        先按 F1 确保英雄选中——背包物品快捷键要求持有物品的 Unit 处于选中状态。
        """
        self._reselect_hero()
        old_feed_time = self.pet_feed_time
        self.combat.feed_pet(self, self._stop_event)
        # feed_pet 内部更新 pet_feed_time，通过时间变化判断是否实际喂食
        if self.pet_feed_time != old_feed_time:
            self._feed_count += 1

    def _report_lines(self):
        """刷新浮窗多行状态：各技能施放次数。"""
        if not self._progress_lines_callback:
            return
        lines = [
            f"{skill.get('name', skill['key'].upper())}：{self._cast_counts.get(skill['key'], 0)} 次"
            for skill in self.skills
        ]
        if self.pet_feed_interval > 0:
            lines.append(f"喂宠物：{self._feed_count} 次")
        self._progress_lines_callback(lines)

    # ── 主流程 ──────────────────────────────────────────

    def run_core(self, hwnd):
        """核心挂机循环 — 假设窗口已绑定。不做走位/开 boss，直接施法 + 喂宠物。"""
        self.war3.set_client_size(hwnd)
        x1, y1, x2, y2 = self.dm.get_client_rect(hwnd)
        self.client_center = [(x2 - x1) // 2, (y2 - y1) // 2]
        self._last_cast = time.monotonic()

        # 喂宠物计时从进挂机循环起算，首次喂食在 feeding_interval 后触发
        self.pet_feed_time = time.time()
        feed_timer = time.time()

        skill_names = "、".join(f"{s['key'].upper()}{s.get('name', '')}" for s in self.skills)
        logger.info(f"风龙挂机开始：技能 {skill_names}，客户区中心 {self.client_center}")

        while True:
            if self._stop_event is not None and self._stop_event.is_set():
                raise StopTaskError("用户请求停止任务")

            # 定时喂宠物：pet_feed_interval 为"是否到喂食时间"的检测间隔，
            # 实际喂食间隔由 jiubing2.toml [pet].feeding_interval（分钟）控制
            if self.pet_feed_interval > 0 and time.time() - feed_timer >= self.pet_feed_interval:
                self._feed_pet()
                feed_timer = time.time()

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
        """绑定参数（按 war3.bind_mode 选择前台/后台参数表）。"""
        bind_cfg = resolve_bind_cfg(self.war3_cfg)
        if bind_cfg.get("bind_mode") == "background":
            logger.info(f"使用后台绑定: {bind_cfg}")
        return bind_cfg

    def _find_war3_hwnd(self) -> int:
        """查找 war3 窗口（委托 War3Business.find_game_window 按绑定模式选择）。"""
        return self.war3.find_game_window()

    def run(self):
        """主入口 — 查找窗口、绑定、统一窗口尺寸、运行挂机循环。"""
        if not self.skills:
            logger.error("未配置技能列表（this.skills）")
            return

        if self.pet_feed_interval > 0 and not get_inventory_hotkeys(self.hero_cfg, 9):
            logger.warning("未装备宠物食物（物品 id=9），定时喂宠物将不会生效")

        hwnd = self._find_war3_hwnd()
        if not hwnd:
            logger.error("未找到 war3 窗口")
            return

        # 尺寸调整放在绑定前：dx2 挂钩后 resize 会重建交换链导致闪屏
        self.war3.set_client_size(hwnd)
        with self.dm.bind_window(hwnd, bind_cfg=self._bind_cfg()):
            self.run_core(hwnd)

        summary = "，".join(f"{k.upper()} {v} 次" for k, v in self._cast_counts.items())
        logger.info(f"风龙挂机结束：{summary or '无施放'}")


def main():
    setup_global_exception_hook()
    # 命令行参数可指定变体配置名（如 wind_dragon_善木木 认领指定玩家窗口）
    # 用法：python -m GameBot.runner.tasks.war3.jiubing2.wind_dragon.wind_dragon wind_dragon_善木木
    base_task_name = "war3.jiubing2.tasks.wind_dragon.wind_dragon"
    task_name = base_task_name
    if len(sys.argv) > 1:
        leaf_arg = sys.argv[1]
        task_name = leaf_arg if "." in leaf_arg else f"war3.jiubing2.tasks.wind_dragon.{leaf_arg}"
    cfg = config.load_task(task_name)

    setup_log_file("风龙挂机")
    logger.info("############################# 风龙挂机 #############################")
    if task_name != base_task_name:
        logger.info(f"使用指定配置: {task_name}")

    def task_wrapper(stop_event, progress_callback=None, **kwargs):
        WindDragonTask(
            cfg,
            task_name=task_name,
            stop_event=stop_event,
            progress_callback=progress_callback,
            progress_lines_callback=kwargs.get("progress_lines_callback"),
        ).run()

    run_with_float_window("风龙挂机", task_wrapper, countdown_seconds=5, float_cfg=cfg.get("base", {}).get("float_window", {}))


if __name__ == "__main__":
    main()
