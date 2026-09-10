"""圣骑士风龙后台绑定参数测试。

运行环境：手动测试，依赖大漠插件 COM 与真实 War3 窗口。
测试不同 display / mouse / keypad / mode 组合下，风龙挂机脚本的
技能图标检测、按键施放、鼠标点击等行为是否正常。

用法：
    uv run python tests/manual/test_paladin_wind_dragon_bind.py
    uv run python tests/manual/test_paladin_wind_dragon_bind.py --duration 20
    uv run python tests/manual/test_paladin_wind_dragon_bind.py --mouse windows2,windows3 --keypad windows
    uv run python tests/manual/test_paladin_wind_dragon_bind.py --display dx2 --mouse windows2 --keypad windows --mode 0

注意事项：
- 需要以管理员权限运行（dx 绑定模式要求，未提权时 windows2 / dx 等模式常报错）
- 测试前请将圣骑士角色置于可释放技能状态（如风龙挂机点）
- 脚本会真实发送按键和点击，请在合适的游戏场景下运行
- 后台绑定下 War3 窗口可被遮挡，但不能最小化
- 多种组合连续测试时，技能会进入冷却，后一组可能检测不到就绪图标；
  可用 --wait-between 在组间等待，或增大 --duration
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import threading
import time
from pathlib import Path

from GameBot.config import config
from GameBot.runner.driver import create_dm_client
from GameBot.runner.tasks.war3.jiubing2.others.paladin_wind_dragon import PaladinWindDragonTask
from GameBot.utils import DmError, StopTaskError, logger, setup_log_file

OUT_DIR = Path("logs/diag_wind_dragon_bind")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 默认测试矩阵：display 固定 dx2，mode 固定 0，
# 主要比较 mouse 与 keypad 设置对游戏行为的影响。
DEFAULT_DISPLAYS = ["dx2"]
DEFAULT_MICE = ["windows", "windows2", "windows3"]
DEFAULT_KEYPADS = ["windows", "dx"]
DEFAULT_PUBLICS = [""]
DEFAULT_MODES = [0]


def _split_arg(value: str | None, defaults: list[str]) -> list[str]:
    """解析逗号分隔的 CLI 参数，未指定时使用默认值。"""
    if value is None:
        return [str(d) for d in defaults]
    return [v.strip() for v in value.split(",") if v.strip()]


def build_test_cases(
    displays: list[str],
    mice: list[str],
    keypads: list[str],
    publics: list[str],
    modes: list[int],
) -> list[dict]:
    """构建大漠绑定组合测试列表。"""
    cases = []
    for display in displays:
        for mouse in mice:
            for keypad in keypads:
                for public in publics:
                    for mode in modes:
                        cases.append({
                            "display": display,
                            "mouse": mouse,
                            "keypad": keypad,
                            "public": public,
                            "mode": mode,
                        })
    return cases


def _inject_test_bind_cfg(base_cfg: dict, case: dict) -> dict:
    """深拷贝配置并注入当前测试的绑定参数。"""
    cfg = copy.deepcopy(base_cfg)
    task_path = cfg["war3"]["jiubing2"]["tasks"]["others"]["paladin_wind_dragon"]
    task_path["bind_mode"] = "background"
    cfg["war3"]["bind_multi"] = {
        "display": case["display"],
        "mouse": case["mouse"],
        "keypad": case["keypad"],
        "public": case.get("public", ""),
        "mode": case["mode"],
        "bind_delay": 1.5,
    }
    return cfg


def run_one_case(
    base_cfg: dict,
    dm,
    case: dict,
    duration: float,
    case_index: int,
    total: int,
) -> dict:
    """对一种后台绑定组合运行风龙挂机循环，返回行为指标。"""
    public = case.get("public", "")
    public_label = f"_public{public.replace('|', '_')}" if public else ""
    label = (
        f"wd_{case['display']}_{case['mouse']}_{case['keypad']}{public_label}_"
        f"mode{case['mode']}"
    )
    logger.info(
        f"\n[{case_index}/{total}] 测试组合: "
        f"display={case['display']}, mouse={case['mouse']}, "
        f"keypad={case['keypad']}, public={public!r}, "
        f"mode={case['mode']}, duration={duration}s"
    )

    result = {
        "label": label,
        "case": case,
        "duration": duration,
        "actual_duration": 0.0,
        "bind_ok": False,
        "detect_ok": False,
        "ready_states": {},
        "casts": {},
        "total_casts": 0,
        "error": "",
    }

    cfg = _inject_test_bind_cfg(base_cfg, case)
    stop_event = threading.Event()
    task = PaladinWindDragonTask(cfg, stop_event=stop_event, dm=dm)

    try:
        hwnd = task._find_war3_hwnd()
        if not hwnd:
            result["error"] = "未找到 war3 窗口"
            logger.error(f"  [{label}] {result['error']}")
            return result

        with dm.bind_window(hwnd, bind_cfg=task._bind_cfg()):
            result["bind_ok"] = True
            logger.info(f"  [{label}] 已绑定窗口 hwnd={hwnd}")

            # 对齐客户区尺寸并计算中心（run_core 需要 client_center）
            task.war3.set_client_size(hwnd)
            x1, y1, x2, y2 = dm.get_client_rect(hwnd)
            task.client_center = [(x2 - x1) // 2, (y2 - y1) // 2]

            # 图标检测：验证 display 模式能否正确截图并识别就绪图标
            for skill in task.skills:
                ready = task._is_ready(skill)
                result["ready_states"][skill["key"]] = ready
                name = skill.get("name", skill["key"].upper())
                status = "就绪" if ready else "未就绪/冷却中"
                logger.info(
                    f"  [{label}] 技能 {name}({skill['key'].upper()}) 检测: {status}"
                )
            result["detect_ok"] = any(result["ready_states"].values())

            # 启动限时计时器并运行挂机循环
            timer = threading.Timer(duration, stop_event.set)
            timer.daemon = True
            timer.start()
            start_time = time.monotonic()
            try:
                task.run_core(hwnd)
            except StopTaskError:
                logger.info(f"  [{label}] 到达测试时长，停止循环")
            finally:
                timer.cancel()
            result["actual_duration"] = round(time.monotonic() - start_time, 2)

        result["casts"] = {k: v for k, v in task._cast_counts.items()}
        result["total_casts"] = sum(result["casts"].values())
        logger.info(
            f"  [{label}] 测试结束，实际运行 {result['actual_duration']}s，"
            f"施放次数: {result['casts']}"
        )

    except DmError as e:
        result["error"] = f"大漠错误: {e}"
        logger.error(f"  [{label}] {result['error']}")
    except Exception as e:
        result["error"] = f"异常: {e}"
        logger.exception(f"  [{label}] {result['error']}")

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="圣骑士风龙后台绑定参数测试")
    parser.add_argument("--delay", type=int, default=5, help="启动前等待秒数（默认 5）")
    parser.add_argument(
        "--duration",
        type=float,
        default=15.0,
        help="每组绑定运行秒数（默认 15）",
    )
    parser.add_argument(
        "--display",
        type=str,
        default=None,
        help="截图模式，多个用逗号分隔",
    )
    parser.add_argument(
        "--mouse",
        type=str,
        default=None,
        help="鼠标仿真模式，多个用逗号分隔",
    )
    parser.add_argument(
        "--keypad",
        type=str,
        default=None,
        help="键盘仿真模式，多个用逗号分隔",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default=None,
        help="绑定 mode，多个用逗号分隔",
    )
    parser.add_argument(
        "--public",
        type=str,
        default=None,
        help='公共属性 dx.public.*，多个用逗号分隔，如 "dx.public.active.api"',
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="JSON 报告输出路径",
    )
    parser.add_argument(
        "--wait-between",
        type=float,
        default=0.0,
        dest="wait_between",
        help="每组测试结束后等待秒数，用于让技能冷却恢复（默认 0）",
    )
    args = parser.parse_args()

    setup_log_file("风龙后台绑定测试")

    logger.info("=" * 60)
    logger.info("圣骑士风龙后台绑定参数测试")
    logger.info("=" * 60)
    logger.info("测试目标：比较不同 mouse/keypad 组合下风龙挂机的键鼠行为")
    logger.info("请提前将圣骑士置于可释放技能状态，并确保 War3 窗口存在")

    # 倒计时
    for i in range(args.delay, 0, -1):
        logger.info(f"{i} 秒后开始...")
        time.sleep(1)

    # 加载并深拷贝风龙任务配置
    base_cfg = config.load_task("war3.jiubing2.tasks.others.paladin_wind_dragon")
    base_cfg = copy.deepcopy(base_cfg)

    # 解析测试矩阵
    displays = _split_arg(args.display, DEFAULT_DISPLAYS)
    mice = _split_arg(args.mouse, DEFAULT_MICE)
    keypads = _split_arg(args.keypad, DEFAULT_KEYPADS)
    publics = _split_arg(args.public, DEFAULT_PUBLICS)
    mode_strs = _split_arg(args.mode, [str(m) for m in DEFAULT_MODES])
    modes = [int(m) for m in mode_strs]

    cases = build_test_cases(displays, mice, keypads, publics, modes)
    if not cases:
        logger.error("没有可测试的组合")
        return 1

    logger.info(f"测试矩阵: {len(cases)} 种组合")
    for c in cases:
        logger.info(f"  {c}")

    dm = create_dm_client()
    try:
        results = []
        for i, case in enumerate(cases, 1):
            result = run_one_case(base_cfg, dm, case, args.duration, i, len(cases))
            results.append(result)
            if i < len(cases) and args.wait_between > 0:
                logger.info(f"  等待 {args.wait_between}s 让技能冷却恢复...")
                time.sleep(args.wait_between)

        # 汇总输出
        logger.info("\n" + "=" * 60)
        logger.info("测试结果汇总")
        logger.info("=" * 60)
        for r in results:
            status = "通过" if r["total_casts"] > 0 else "未施放/失败"
            logger.info(
                f"{r['label']}: {status} | "
                f"bind={r['bind_ok']} detect={r['detect_ok']} "
                f"casts={r['total_casts']} ({r['casts']}) | "
                f"error={r['error'] or '无'}"
            )

        # 保存 JSON 报告
        report_path = Path(args.output) if args.output else OUT_DIR / "report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logger.info(f"\n报告已保存: {report_path.resolve()}")

        # 只要有一组成功施放即视为测试有有效结果
        return 0 if any(r["total_casts"] > 0 for r in results) else 1
    finally:
        dm.close()


if __name__ == "__main__":
    sys.exit(main())
