"""装备卡牌（GameUI.equip_cards）后台绑定模式实测脚本。

前置条件：War3 已在游戏中且已选好英雄（处于可按 F4 打开卡牌窗口的状态），
窗口不可最小化。单开场景（只运行一个 war3 窗口）。

多开场景（多个 war3 窗口）须传变体任务名，认领走聊天 token 归属验证：
    uv run python tests/manual/test_equip_cards.py endless_善木木

用法：
    uv run python tests/manual/test_equip_cards.py [任务名，默认 endless]

流程：
1. find_game_window 认领 war3 窗口（后台模式走命名互斥锁，单开即取即得）
2. set_client_size → bind_window（后台绑定参数）
3. 诊断：F4 开一次窗 → 在 card_show_area_coords 内计算 card_show.bmp 实际
   匹配分并存区域截图到 logs/diag_equip_cards/ → F4 关窗
   （分数低于 card_show_sim 说明检测阈值/截图内容有问题，equip_cards 会
   陷入"按 F4 → 找不到 → 再按 F4"的反复开关循环）
4. equip_cards：F4 开窗 → open_timeout 内 WGC 找图确认 → 逐张点击 → 确定 → F4 关窗

浮窗倒计时结束开始，NumPad- 随时停止。
"""

import sys
import time
from pathlib import Path

import numpy as np

from GameBot.config import config, force_bind_mode, get_task_view, resolve_bind_cfg
from GameBot.runner.business.war3 import War3Business
from GameBot.runner.business.war3.jiubing2 import GameUI
from GameBot.runner.driver import create_dm_client
from GameBot.runner.driver.visual import _parse_rgb
from GameBot.runner.ui import run_with_float_window
from GameBot.utils import logger, setup_log_file

OUT_DIR = Path("logs/diag_equip_cards")


def diagnose_card_detect(dm, card_cfg: dict) -> float:
    """开一次卡牌窗口，实测 card_show.bmp 在检测区的最佳匹配分，留存截图。

    先检测窗口当前状态：已打开则直接测量不按 F4（开关切换键，已开时再按
    会把它关掉）；未打开才按 F4 开窗。测量达标后窗口保持打开交给
    equip_cards 直接使用，不再关掉重开；仅测量失败（调用方中止）时
    由本函数按开的窗关窗还原。

    :return: 最佳匹配分（0~1）
    """
    hotkey = card_cfg["switch_hotkey"]
    area = card_cfg["card_show_area_coords"]
    delta_color = card_cfg.get("card_show_delta_color", "000000")
    tol = _parse_rgb(delta_color)
    already_open = dm.find_pic(
        *area, card_cfg["card_show_img"],
        sim=card_cfg["card_show_sim"], delta_color=delta_color,
    )[0] > -1
    if already_open:
        logger.info("卡牌窗口已打开，直接测量匹配分（不按 F4）")
    else:
        dm.key_press_char(hotkey)
        time.sleep(1.2)  # 等卡牌窗口渲染出来
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    area_shot = OUT_DIR / "card_area.png"
    full_shot = OUT_DIR / "full_frame.png"
    dm.capture_region(*area, str(area_shot))
    dm._wgc().save(str(full_shot))
    # 与 find_pic 同一实现：模板中落在 delta_color 容差内的像素占比
    region = dm._wgc().grab_client_rgb(tuple(area))
    tpl = dm._load_template(card_cfg["card_show_img"])
    scores = dm._match_scores(region, tpl, tol)
    pos = np.unravel_index(int(np.argmax(scores)), scores.shape)
    best = float(scores[pos])
    logger.info(
        f"card_show 最佳匹配分 {best:.3f}（阈值 {card_cfg['card_show_sim']}），"
        f"位置 ({area[0] + pos[1]}, {area[1] + pos[0]})，"
        f"截图: {area_shot} / {full_shot}"
    )
    # 测量失败即将中止：若窗口是本函数按开的，按一次关窗还原
    if not already_open and best < card_cfg["card_show_sim"]:
        dm.key_press_char(hotkey)
        time.sleep(0.5)
    return best


def main():
    setup_log_file("装备卡牌测试")
    logger.info("############################# 装备卡牌测试 #############################")

    leaf_arg = sys.argv[1] if len(sys.argv) > 1 else "endless"
    task_name = leaf_arg if "." in leaf_arg else f"war3.jiubing2.tasks.endless.{leaf_arg}"
    cfg = config.load_task(task_name)
    force_bind_mode(cfg, "background")

    war3_cfg = cfg.get("war3", {})
    hero_cfg = cfg.get("hero", {})
    card_cfg = cfg["war3"]["jiubing2"]["card"]
    logger.info(f"卡牌 use_index={hero_cfg.get('card', {}).get('use_index')}")

    dm = create_dm_client()
    war3 = War3Business(dm, war3_cfg)
    # 多开认领：变体 [this] target_player 注入 war3，认领走聊天 token 归属验证
    war3.target_player = get_task_view(cfg, task_name).get("target_player", "")
    ui = GameUI(dm, war3_cfg, hero_cfg, cfg, war3)

    def run(stop_event, progress_callback=None):
        hwnd = war3.find_game_window()
        if not hwnd:
            logger.error("未找到 war3 窗口，测试终止")
            return
        logger.info(f"war3 窗口 hwnd={hwnd}，绑定参数: {resolve_bind_cfg(war3_cfg)}")

        war3.set_client_size(hwnd)
        with dm.bind_window(hwnd, bind_cfg=resolve_bind_cfg(war3_cfg)):
            best = diagnose_card_detect(dm, card_cfg)
            if best < card_cfg["card_show_sim"]:
                logger.error(
                    f"匹配分 {best:.3f} 低于阈值 {card_cfg['card_show_sim']}，"
                    "equip_cards 会找不到窗口陷入反复开关循环——"
                    "请打开 logs/diag_equip_cards/card_area.png 比对模板后调低 "
                    "card_show_sim 或修正 card_show_area_coords，再重新运行"
                )
                return
            ui.equip_cards(stop_event=stop_event)
        logger.info("equip_cards 执行完毕，请核对游戏内卡牌装备结果")

    run_with_float_window(
        "装备卡牌测试",
        run,
        countdown_seconds=5,
        float_cfg=cfg.get("base", {}).get("float_window", {}),
    )


if __name__ == "__main__":
    main()
