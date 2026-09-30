"""
刷局数 — 多局挂机任务：KK → War3 → 选难度 → 挂机 idle_time 秒 → 退出 → 循环

参考多局无尽（endless.py），但选完难度后不再做任何操作，挂满配置时长
（默认 630s）后直接退出本局，用于刷账号局数统计。

多开用法（本机两个玩家各跑各的刷局数，互不干扰）：
    uv run python -m GameBot.runner.tasks.war3.jiubing2.others.game_count game_count_善木木
变体配置 tasks/others/game_count_<玩家名>.toml 需写 target_player、
[war3]/[kk] bind_mode="background"（多开必须后台绑定）等差异字段：
- KK 侧：认领本账号房间窗口——聊天输入框发随机 token，OCR 聊天记录区"玩家名：token"
  提取归属；认领后拿到 owner_pid，弹窗/掉线处理全按 PID 过滤
- War3 侧：加载页只读认领（WGC OCR 玩家列表 + 内核互斥锁，读图期对窗口
  零操作），进游戏后等待→统一尺寸→绑定→按本账号配置选难度。实测读图期
  对窗口注入 dx 绑定会使多开另一实例卡死加载页；难度界面在场时无法发
  聊天 token 验归属（Enter 会误选默认难度），故认领必须在加载页完成
- 任一认领失败任务直接停止，避免误操作另一账号窗口
启动要求：账号停留在 KK 房间内（创建好密码房即可运行）
"""

import sys
import time

from GameBot.config import config, get_task_view, resolve_bind_cfg
from GameBot.inference import get_inference_client
from GameBot.runner import create_dm_client
from GameBot.runner.business.kk import KKBusiness
from GameBot.runner.business.war3 import War3Business
from GameBot.runner.business.war3.jiubing2 import GameUI
from GameBot.runner.ui import run_with_float_window
from GameBot.utils import StopTaskError, WindowLostError, logger, setup_log_file
from GameBot.utils.exception_handler import CaptureError, setup_global_exception_hook


class GameCountTask:
    """刷局数任务（多局挂机：选完难度挂机到时长即退出）"""

    def __init__(self, cfg: dict, task_name: str = "war3.jiubing2.tasks.others.game_count"):
        self.task_cfg = cfg
        self.dm = create_dm_client()
        # 任务视图：沿 extends 链深合并（game_count → 变体）
        game_cfg = get_task_view(cfg, task_name)

        war3_cfg = self.task_cfg.get("war3", {})
        hero_cfg = self.task_cfg.get("hero", {})
        kk_cfg = self.task_cfg.get("kk", {})

        self.war3 = War3Business(self.dm, war3_cfg)
        self.kk = KKBusiness(self.dm, kk_cfg)
        self.ui = GameUI(self.dm, war3_cfg, hero_cfg, self.task_cfg, self.war3)
        self.game_cfg = game_cfg
        self.war3_cfg = war3_cfg

        # 多开认领：target_player 在变体 [this] 里配置，注入 war3 供 find_game_window/claim 链路读取
        self.target_player = game_cfg.get("target_player", "")
        self.war3.target_player = self.target_player
        # 本账号 KK 房间窗口与进程 PID（多开认领缓存，全链路按 PID 过滤）
        self.room_hwnd = 0
        self.owner_pid = 0

        self.game_start_time = 0
        self.pet_feed_time = 0

    def _claim_kk_room(self) -> None:
        """认领本账号 KK 房间窗口（聊天 token 归属识别），缓存 room_hwnd 与 owner_pid。

        claim_room_window 内部已处理认领复用（窗口存活且 PID 一致直接返回），
        认领失败抛错终止任务——多开必须确认归属，否则可能操作到另一账号窗口。
        """
        room_hwnd, owner_pid = self.kk.claim_room_window(
            self.dm, self.target_player, stop_event=self._stop_event
        )
        if not room_hwnd:
            raise RuntimeError(f"未认领到归属 {self.target_player} 的 KK 房间窗口，任务停止")
        self.room_hwnd, self.owner_pid = room_hwnd, owner_pid

    def do_kk(self) -> bool:
        """KK 阶段：找到/创建本账号房间并开始游戏。

        :return: True=已点击开始游戏, False=跳过本局
        """
        if self.target_player:
            # 多开：认领本账号房间（失败抛错终止），弹窗按 PID 过滤后在认领窗口点开始
            self._claim_kk_room()
            self.kk.dismiss_room_popups(self.dm, owner_pid=self.owner_pid)
            return self.kk.start_game(self.dm, room_hwnd=self.room_hwnd, stop_event=self._stop_event)
        # 先尝试找到已有房间
        room_hwnd = self.kk.dismiss_room_popups(self.dm)
        if room_hwnd:
            # 找到房间，直接开始游戏（传入 room_hwnd 避免重复检测）
            return self.kk.start_game(self.dm, room_hwnd=room_hwnd, stop_event=self._stop_event)
        # 未找到房间，清理主界面弹窗后创建
        logger.info("未找到 KK 房间，开始自动创建房间")
        self.kk.dismiss_hall_popups(self.dm)
        map_name = self.task_cfg.get("war3", {}).get("jiubing2", {}).get("game", {}).get("map_name", "九种兵器2诸神战场")
        room_hwnd = self.kk.create_room(self.dm, map_name=map_name)
        if not room_hwnd:
            logger.error(
                "创建房间失败，跳过本局。建议检查：1) KK 主界面是否正常显示 2) 搜索结果是否包含目标地图 3) 创建房间弹窗是否出现 4) 网络是否正常"
            )
            return False
        return self.kk.start_game(self.dm, room_hwnd=room_hwnd, stop_event=self._stop_event)

    def _interruptible_wait(self, seconds: float):
        """可被停止信号中断的等待，检测到停止时抛出 StopTaskError。"""
        if self._stop_event is not None:
            if self._stop_event.wait(seconds):
                raise StopTaskError("用户请求停止任务")
        else:
            time.sleep(seconds)

    def _identify_claim_window(self, hwnd: int) -> str:
        """认领归属验证（只读优先，按窗口所处阶段选择方式）——多局任务认领模式。

        与多局无尽一致：多局任务窗口随每局重开，认领须赶在加载页完成。

        - 加载页：OCR 玩家列表判归属（纯 WGC 读帧，对窗口零操作）
        - 已进游戏：发聊天 token 验证（内部自行对齐尺寸并绑定）
        - 已进游戏但难度选择界面在场：返回 "" 跳过本轮——此时 Enter 会误选
          默认难度而非打开聊天框，token 不可用（不同账号难度可能不同，
          绝不能在归属未确认时触碰难度界面）
        """
        try:
            if not self.war3.is_in_game(hwnd):
                return self.war3.identify_war3_owner(hwnd)
            if self.ui.is_difficulty_visible(hwnd):
                logger.debug(f"war3 窗口 {hwnd} 难度选择界面在场，本轮无法发 token 验归属")
                return ""
            return self.war3._identify_owner_by_chat(hwnd, self._stop_event)
        except CaptureError:
            return ""  # WGC 会话尚无帧/窗口将销毁等瞬时失败，本轮跳过下轮再试

    def _idle_in_game(self, hwnd: int, seconds: float, game_idx: int, games: int) -> None:
        """选完难度后挂机等待满时长（分片可中断，周期检测认领窗口存活）。

        :param hwnd: 本局认领的 war3 窗口
        :param seconds: 挂机总时长（秒）
        :raises WindowLostError: 挂机期间窗口消失（掉线）
        :raises StopTaskError: 收到停止信号
        """
        deadline = time.time() + seconds
        logger.info(f"进入挂机，{seconds:.0f}s 后退出本局")
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                return
            self._interruptible_wait(min(10.0, remaining))
            if not self.war3._find_war3_hwnd():
                raise WindowLostError("挂机期间 War3 窗口消失，可能掉线")
            self._progress_callback(f"第 {game_idx}/{games} 局 - 挂机中 剩余 {int(deadline - time.time())}s")

    def do_war3(self, game_idx, games) -> bool:
        """执行单局 War3 流程：认领 → 等进游戏 → 选难度 → 挂机 → 退出。

        :return: True=本局正常完成, False=本局异常已跳过
        """
        logger.debug("已进入war3，等待地图加载")
        # 读图期对 war3 窗口零操作（与手动启动一致）：加载页只做只读 OCR 认领
        # + 内核互斥锁（不占窗口、不改尺寸、不绑定、不注入）。实测两个实例读图
        # 重叠时对窗口改尺寸/注入 dx 绑定会使其中一方卡死加载页。
        # 认领必须在加载页完成：难度界面在场时无法发聊天 token 验归属
        # （Enter 会误选默认难度），且各账号难度可能不同，必须先验归属再选难度。
        # 上局窗口随 quit_game 销毁，先释放旧认领。
        self.war3.release_war3_claim()
        claim_timeout = float(self.war3_cfg.get("wait_for_game_window", {}).get("timeout", 60)) + float(
            self.war3_cfg.get("in_game_detect", {}).get("timeout", 120)
        )
        hwnd = self.war3.claim_war3_window(
            self.target_player,
            stop_event=self._stop_event,
            claim_timeout=claim_timeout,
            identify=self._identify_claim_window,
        )
        if not hwnd:
            if self.target_player:
                # 认领失败直接终止——归属未确认时继续运行可能误操作另一账号窗口。
                # 注意不能对未认领窗口发退出键清场：未进游戏的窗口可能属于其他玩家
                raise RuntimeError(f"未认领到归属 {self.target_player} 的 War3 窗口，任务停止")
            # 单开兜底：未进游戏的窗口必属本机玩家，发退出键清场后下轮重开
            self._quit_stuck_war3_windows()
            logger.error("未找到 War3 窗口，跳过本局")
            self._handle_kk_disconnect()
            return False
        # 等进游戏：无绑定 WGC 轮询，读图期不触碰窗口
        try:
            self.war3.wait_enter_game(self, self._stop_event, hwnd=hwnd)
        except TimeoutError as e:
            logger.error(f"卡在加载界面，关闭 War3：{e}")
            # 窗口已认领为本账号（持互斥锁），可安全绑定发退出键
            with self.dm.bind_window(hwnd, bind_cfg=resolve_bind_cfg(self.war3_cfg)):
                self.war3.quit_game()
            return False
        except WindowLostError:
            logger.error("掉线，War3 窗口消失")
            self._handle_kk_disconnect()
            return False
        self.war3.set_client_size(hwnd)
        idle_time = float(self.game_cfg.get("idle_time", 630))
        try:
            with self.dm.bind_window(hwnd, bind_cfg=resolve_bind_cfg(self.war3_cfg)):
                # 进游戏后按本账号配置选难度（界面不在场则跳过）
                if self.ui.wait_and_select_difficulty(hwnd, self.game_cfg, self._stop_event):
                    logger.info("难度选择完成")
                else:
                    logger.warning("难度选择界面未出现或未命中目标，继续挂机")
                # 挂机满 idle_time 即退出；挂机期间掉线抛 WindowLostError
                self._idle_in_game(hwnd, idle_time, game_idx, games)
                self.war3.quit_game()
        except WindowLostError:
            logger.error("掉线，War3 窗口消失")
            self._handle_kk_disconnect()
            return False

        self._interruptible_wait(self.game_cfg.get("loop_interval_time", 5))
        return True

    def _handle_kk_disconnect(self) -> None:
        """检测并处理 KK 掉线重连弹窗（多开时按本账号 PID 过滤）。"""
        self.kk.handle_disconnect_dialog(self.dm, owner_pid=self.owner_pid)

    def _quit_stuck_war3_windows(self) -> None:
        """单开兜底：对所有未认领 war3 窗口发退出键，清理可能卡死加载页的窗口。

        仅在单开路径调用（target_player 为空）——此时本机所有 war3 窗口均属
        本玩家，可直接操作；多开路径绝不可调用（未认领窗口可能属于其他玩家）。
        """
        wins = self.dm.find_windows(self.war3_cfg.get("window_class", ""), self.war3_cfg.get("window_title", ""))
        for w in wins:
            hwnd = w["hwnd"]
            try:
                with self.dm.bind_window(hwnd, bind_cfg=resolve_bind_cfg(self.war3_cfg)):
                    self.war3.quit_game()
            except Exception as e:
                logger.warning(f"清理疑似卡死 war3 窗口 {hwnd} 失败：{e}")

    def run(self, stop_event=None, progress_callback=None):
        self._stop_event = stop_event
        self._progress_callback = progress_callback or (lambda text: None)
        games = self.game_cfg.get("games", 10)
        idle_time = float(self.game_cfg.get("idle_time", 630))
        logger.info(f"游戏总局数：{games}，每局挂机时长：{idle_time:.0f}s")
        try:
            for game_idx in range(1, games + 1):
                self._progress_callback(f"第 {game_idx}/{games} 局 - 准备中")
                if self.do_kk():
                    self.do_war3(game_idx, games)
        except StopTaskError:
            logger.info("收到停止信号，停止刷局数")
        logger.info("刷局数任务结束")


def main():
    setup_global_exception_hook()
    # 命令行参数可指定变体配置名（如 game_count_善木木 认领指定玩家窗口）
    # 用法：python -m GameBot.runner.tasks.war3.jiubing2.others.game_count game_count_善木木
    task_name = "war3.jiubing2.tasks.others.game_count"
    if len(sys.argv) > 1:
        leaf_arg = sys.argv[1]
        task_name = leaf_arg if "." in leaf_arg else f"war3.jiubing2.tasks.others.{leaf_arg}"
    cfg = config.load_task(task_name)

    # 显示名动态计算：变体配置带 target_player 时拼上玩家名
    target_player = get_task_view(cfg, task_name).get("target_player", "")
    title = f"刷局数-{target_player}" if target_player else "刷局数"

    setup_log_file(title)
    logger.info(f"############################# {title} #############################")
    if task_name != "war3.jiubing2.tasks.others.game_count":
        logger.info(f"使用指定配置: {task_name}")

    # 预加载 OCR（认领/选难度需要 OCR，不需要宝箱和战斗模型）
    get_inference_client(load_chest=False, load_combat=False)

    def task_wrapper(stop_event, progress_callback=None):
        GameCountTask(cfg, task_name=task_name).run(stop_event=stop_event, progress_callback=progress_callback)

    run_with_float_window(title, task_wrapper, countdown_seconds=5, float_cfg=cfg.get("base", {}).get("float_window", {}))


if __name__ == "__main__":
    main()
