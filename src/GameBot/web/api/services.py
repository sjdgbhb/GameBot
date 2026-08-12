"""Web 服务层 — 从旧 server.py 提取的纯业务逻辑。

不包含任何 HTTP 处理代码，可被路由层直接调用。
"""
import copy
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

# 项目根目录：web/api/services.py → web/api/ → web/ → GameBot/ → src/ → 项目根
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_CONFIG_DIR = _PROJECT_ROOT / "src" / "GameBot" / "config" / "data"

# 从 web.toml 读取配置
_WEB_CONFIG_PATH = _CONFIG_DIR / "web.toml"
_WEB_CONFIG = {}
try:
    with open(_WEB_CONFIG_PATH, "rb") as f:
        _WEB_CONFIG = tomllib.load(f).get("web", {})
except Exception:
    pass

WEB_HOST = _WEB_CONFIG.get("host", "127.0.0.1")
WEB_PORT = int(_WEB_CONFIG.get("port", 18080))
USER_CONFIGS_PATH = _PROJECT_ROOT / _WEB_CONFIG.get("user_configs", "user_configs.json")

# 任务进程跟踪（task_id -> Popen）
_running_processes = {}

# 任务图标映射（任务短 ID -> emoji 图标）
_TASK_ICONS = {
    "patrol_loot": "⚔",
    "fishing": "🎣",
    "endless": "∞",
    "endless_single": "∞",
}

# 分类图标
_CATEGORY_ICONS = {
    "achievements": "🏆",
    "atomic": "⚡",
    "reputation": "🏅",
    "endless": "∞",
    "others": "📦",
}

_HERO_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def _task_icon(task_id: str) -> str:
    """根据任务 ID 返回图标，优先短 ID 特殊映射，否则按分类。"""
    short = task_id.split(".")[-1]
    if short in _TASK_ICONS:
        return _TASK_ICONS[short]
    category = task_id.split(".")[0] if "." in task_id else ""
    return _CATEGORY_ICONS.get(category, "📜")


def _task_module_path(task_id: str) -> Path:
    """根据任务 ID（如 others.patrol_loot）推导源码文件路径。

    新目录结构：runner/tasks/war3/jiubing2/<task_id>.py
    """
    return _PROJECT_ROOT / "src" / "GameBot" / "runner" / "tasks" / "war3" / "jiubing2" / Path(*task_id.split(".")).with_suffix(".py")


def is_runnable_task(task_id: str) -> bool:
    """检查任务 ID 是否对应 src/GameBot/tasks 下的可执行脚本。"""
    if not re.match(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$", task_id):
        return False
    return _task_module_path(task_id).exists()


def _find_task_section(data: dict) -> dict:
    """在 TOML 的 [war3.jiubing2.tasks.xxx] 命名空间中找到叶子任务节点（含 name 的字典）。"""
    section = data.get("war3", {}).get("jiubing2", {}).get("tasks", {})
    while isinstance(section, dict):
        if "name" in section:
            return section
        sub = None
        for v in section.values():
            if isinstance(v, dict):
                sub = v
                break
        if sub is None:
            break
        section = sub
    return {}


def load_tasks() -> list:
    """扫描 tasks/ 目录，提取任务 ID、名称、图标和描述。"""
    tasks_dir = _CONFIG_DIR / "war3" / "jiubing2" / "tasks"
    result = []
    if not tasks_dir.is_dir():
        return result
    # 从前端隐藏的子任务（作为每日声望的子任务被编排，不需要单独展示）
    _HIDDEN_TASKS = set()
    for toml_path in sorted(tasks_dir.rglob("*.toml")):
        rel = toml_path.relative_to(tasks_dir)
        task_id = ".".join(rel.with_suffix("").parts)
        if task_id in _HIDDEN_TASKS:
            continue
        try:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
        except Exception:
            continue
        section = _find_task_section(data)
        name = section.get("name", task_id) if isinstance(section, dict) else task_id
        desc = section.get("description") or section.get("guide") or "" if isinstance(section, dict) else ""
        icon = _task_icon(task_id)
        short_id = task_id.split(".")[-1]
        # 是否已在前端开放配置：TASK_SCHEMAS 中存在完整 task_id 或短 id
        configurable = task_id in TASK_SCHEMAS or short_id in TASK_SCHEMAS
        parts = task_id.split(".")
        result.append({
            "id": task_id,
            "short_id": parts[-1],
            "category": parts[0] if len(parts) > 1 else "",
            "name": name,
            "icon": icon,
            "description": desc,
            "configurable": configurable,
        })
    return result


def load_task_defaults(task_id: str) -> dict:
    """从任务 TOML 读取表单默认值。

    返回 { hero, inventory, desired_items, patrol_rounds, points, chest,
            upgrade_config, mean 等 }：
    - hero: dependencies 中 heroes.<name> 的英雄 id
    - inventory: tasks.<task_id>.inventory（任务级可覆盖英雄配置），未指定则取英雄默认 inventory
    - desired_items: tasks.<task_id>.desired_items
    - patrol_rounds: tasks.<task_id>.patrol.rounds
    - points: tasks.<task_id>.points
    - chest: 顶层 [chest]（覆盖项）
    - upgrade_config: 圣痕待升级配置
    - mean: 圣痕单次升级期望增益
    """
    toml_path = _CONFIG_DIR / "war3" / "jiubing2" / "tasks" / Path(*task_id.split(".")).with_suffix(".toml")
    if not toml_path.exists():
        return {}
    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return {}

    defaults = {}

    # 默认英雄：从 dependencies 中找 war3.jiubing2.heroes.xxx
    dependencies = data.get("dependencies", [])
    for dep in dependencies:
        if isinstance(dep, str) and dep.startswith("war3.jiubing2.heroes."):
            defaults["hero"] = dep.split("war3.jiubing2.heroes.", 1)[1]
            break

    # 若默认英雄没有技能（如占位 heroes.mk），UI 默认选中第一个有技能的英雄，
    # 确保自动施法模式下的英雄选择能直接展示可用技能池。
    if defaults.get("hero"):
        heroes = load_heroes()
        current = next((h for h in heroes if h["id"] == defaults["hero"]), None)
        if not current or not current.get("skills"):
            first_with_skills = next((h for h in heroes if h.get("skills")), None)
            if first_with_skills:
                defaults["hero"] = first_with_skills["id"]

    # 定位任务节点
    task_cfg = _find_task_section(data)

    if isinstance(task_cfg, dict):
        if "inventory" in task_cfg:
            defaults["inventory"] = task_cfg["inventory"]
        if "desired_items" in task_cfg:
            defaults["desired_items"] = task_cfg["desired_items"]
        if "patrol" in task_cfg and isinstance(task_cfg["patrol"], dict) and "rounds" in task_cfg["patrol"]:
            defaults["patrol_rounds"] = task_cfg["patrol"]["rounds"]
        if "points" in task_cfg:
            defaults["points"] = task_cfg["points"]
        if "route_scheme" in task_cfg:
            defaults["route_scheme"] = task_cfg["route_scheme"]
        if "route_presets" in task_cfg:
            defaults["route_presets"] = task_cfg["route_presets"]
            # 从 route_presets 中按 route_scheme 提取默认路线点
            scheme = task_cfg.get("route_scheme", "")
            if scheme:
                for preset in task_cfg["route_presets"]:
                    if isinstance(preset, dict) and preset.get("name") == scheme:
                        defaults["points"] = preset.get("points", [])
                        break
        for k in ("task_times", "loop_interval_time", "clear_nearby_probability",
                  "result_timeout", "result_check_interval", "return_walk_time",
                  "success_text", "fail_text", "enable_blackstone", "enable_forest"):
            if k in task_cfg:
                defaults[k] = task_cfg[k]
        if "mean" in task_cfg:
            defaults["mean"] = task_cfg["mean"]
        if "upgrade_config" in task_cfg and isinstance(task_cfg["upgrade_config"], dict):
            defaults["upgrade_config"] = task_cfg["upgrade_config"]
        # 钓鱼任务字段
        for k in ("max_times", "fishing_interval_time",
                   "mode", "hook_coords"):
            if k in task_cfg:
                defaults[k] = task_cfg[k]
        # 钓鱼 check 子表
        if "check" in task_cfg and isinstance(task_cfg["check"], dict):
            defaults["check"] = task_cfg["check"]

    # 升级圣痕等任务复用城门骚扰路线点作为默认值
    if "points" not in defaults and "war3.jiubing2.tasks.atomic.blackstone_gate_harassment" in dependencies:
        atomic_path = _CONFIG_DIR / "war3" / "jiubing2" / "tasks" / "atomic" / "blackstone_gate_harassment.toml"
        if atomic_path.exists():
            try:
                with open(atomic_path, "rb") as f:
                    atomic_data = tomllib.load(f)
                atomic_cfg = _find_task_section(atomic_data)
                if isinstance(atomic_cfg, dict) and "points" in atomic_cfg:
                    defaults["points"] = atomic_cfg["points"]
            except Exception:
                pass

    # 每日声望：加载黑石城和森之城的原子任务路线点
    if task_id in ("daily_reputation", "reputation.daily_reputation"):
        # 默认物品栏：第 5 格传送卷轴，第 6 格拾取，其他空
        defaults["inventory"] = [
            {"id": -1, "hotkey": "1"},
            {"id": -1, "hotkey": "2"},
            {"id": -1, "hotkey": "3"},
            {"id": -1, "hotkey": "4"},
            {"id": 5, "hotkey": "5"},   # 传送至远古森林外围入口的卷轴
            {"id": 0, "hotkey": "6"},   # 拾取
        ]
        for _atomic_file, _points_key in (
            ("blackstone_gate_harassment", "blackstone_points"),
            ("swift_beast", "forest_points"),
        ):
            _atomic_path = _CONFIG_DIR / "war3" / "jiubing2" / "tasks" / "atomic" / f"{_atomic_file}.toml"
            if _atomic_path.exists():
                try:
                    with open(_atomic_path, "rb") as f:
                        _atomic_data = tomllib.load(f)
                    _atomic_cfg = _find_task_section(_atomic_data)
                    if isinstance(_atomic_cfg, dict):
                        if "points" in _atomic_cfg:
                            defaults[_points_key] = _atomic_cfg["points"]
                except Exception:
                    pass

    # 顶层 hero.inventory（如钓鱼任务不依赖英雄但自带物品栏配置）
    if "inventory" not in defaults:
        hero_cfg = data.get("hero", {})
        if isinstance(hero_cfg, dict) and "inventory" in hero_cfg:
            defaults["inventory"] = hero_cfg["inventory"]

    # 顶层可继承的 chest 覆盖
    if "chest" in data:
        defaults["chest"] = data["chest"]

    return defaults


def load_farmable_items() -> list:
    """从 patrol_loot.toml 读取可刷取装备列表。"""
    defaults = load_task_defaults("others.patrol_loot")
    desired = defaults.get("desired_items", [])
    return [it["name"] for it in desired if isinstance(it, dict) and it.get("name")]


def load_heroes() -> list:
    """扫描 heroes/ 目录，提取英雄 ID、中文名、floor_key。"""
    heroes_dir = _CONFIG_DIR / "war3" / "jiubing2" / "heroes"
    result = []
    if not heroes_dir.is_dir():
        return result
    for toml_path in sorted(heroes_dir.glob("*.toml")):
        hero_id = toml_path.stem
        name = hero_id
        floor_key = "P"
        inventory = []
        skills = []
        try:
            with open(toml_path, "rb") as f:
                raw = f.read()
            content = raw.decode("utf-8", errors="replace")
            data = tomllib.loads(content)
            hero_data = data.get("hero", {})
            floor_key = hero_data.get("floor_key", "P")
            inventory = hero_data.get("inventory", [])
            skills = hero_data.get("skills", [])
            if hero_data.get("name"):
                name = hero_data["name"]
            else:
                m = re.search(r"#{3,}\s*(.+?)\s*#{3,}", content)
                if m:
                    name = m.group(1).strip()
                else:
                    m = re.search(r"英雄配置[：:]\s*\w+\s*[（(](.+?)[）)]", content)
                    if m:
                        name = m.group(1).strip()
                    else:
                        m = re.search(r"英雄配置[：:]\s*(.+)", content)
                        if m:
                            name = m.group(1).strip()
        except Exception:
            pass
        result.append({
            "id": hero_id,
            "name": name,
            "floor_key": floor_key,
            "inventory": inventory,
            "skills": skills,
        })

    # 按楼层和名称排序
    floor_order = {'P': 1, 'O': 2}
    result.sort(key=lambda h: (floor_order.get(h.get("floor_key", "P"), 99), (h.get("name") or h.get("id") or "")))
    return result


def load_items() -> list:
    """从 war3/jiubing2/base.toml 读取物品定义表。"""
    jiubing2_path = _CONFIG_DIR / "war3" / "jiubing2" / "base.toml"
    if not jiubing2_path.exists():
        return []
    with open(jiubing2_path, "rb") as f:
        data = tomllib.load(f)
    items = data.get("items", [])
    return [{"id": it["id"], "name": it["name"]} for it in items]


def load_commands() -> list:
    """从 war3/jiubing2/base.toml 读取 [command] 段，返回指令键值对列表。"""
    jiubing2_path = _CONFIG_DIR / "war3" / "jiubing2" / "base.toml"
    if not jiubing2_path.exists():
        return []
    with open(jiubing2_path, "rb") as f:
        data = tomllib.load(f)
    commands = data.get("command", {})
    return [{"key": k, "cmd": v} for k, v in commands.items()]


def load_user_configs() -> dict:
    """读取 user_configs.json，兼容旧格式。"""
    if USER_CONFIGS_PATH.exists():
        try:
            with open(USER_CONFIGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 兼容旧多配置格式
            if isinstance(data, dict) and "active" in data and "configs" in data:
                active = data.get("active", "default")
                data = data.get("configs", {})
                data = data.get(active, {}) if isinstance(data, dict) else {}
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def save_user_configs(data: dict) -> None:
    """保存 user_configs.json。"""
    with open(USER_CONFIGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_hero_inventory(hero_id: str, inventory: list) -> None:
    """将英雄默认物品栏写回对应英雄 TOML 的 [[hero.inventory]] 段。

    只替换 inventory 数组块，保留文件中其它所有内容（含注释）。
    """
    if not _HERO_ID_RE.match(hero_id):
        raise ValueError(f"非法英雄 ID: {hero_id}")

    toml_path = _CONFIG_DIR / "war3" / "jiubing2" / "heroes" / f"{hero_id}.toml"
    if not toml_path.exists():
        raise FileNotFoundError(f"英雄配置不存在: {toml_path}")

    # 规范化：过滤空格子
    inv = []
    for it in inventory:
        if not isinstance(it, dict):
            continue
        hotkey = str(it.get("hotkey", "")).strip()
        if not hotkey:
            continue
        id_ = it.get("id")
        if id_ is None or id_ == -1:
            continue
        slot = it.get("slot")
        if slot is None:
            slot = int(hotkey) - 1 if hotkey.isdigit() else 0
        inv.append({"slot": int(slot), "id": int(id_), "hotkey": hotkey})
    inv.sort(key=lambda x: x["slot"])

    block_lines = []
    for it in inv:
        block_lines.append("[[hero.inventory]]\n")
        block_lines.append(f'slot = {it["slot"]}\n')
        block_lines.append(f'id = {it["id"]}\n')
        block_lines.append(f'hotkey = "{it["hotkey"]}"\n')
        block_lines.append("\n")
    if not block_lines:
        block_lines.append("# 当前英雄未配置物品栏\n")

    with open(toml_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    start = None
    for i, line in enumerate(lines):
        if line.strip() == "[[hero.inventory]]":
            start = i
            break

    if start is None:
        new_lines = list(lines)
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        new_lines.append("\n")
        new_lines.append("# ------------------------------ 物品栏配置（背包1-6格） ------------------------------\n")
        new_lines.extend(block_lines)
    else:
        end = len(lines)
        for i in range(start + 1, len(lines)):
            stripped = lines[i].strip()
            if stripped.startswith("#") and ("----" in stripped or "====" in stripped):
                end = i
                break
            if stripped.startswith("[") and not stripped.startswith("[[hero.inventory]]"):
                end = i
                break
        new_lines = lines[:start] + block_lines + lines[end:]

    with open(toml_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def export_hero_config(hero_id: str) -> str:
    """读取英雄 TOML 配置文件内容并返回。"""
    if not _HERO_ID_RE.match(hero_id):
        raise ValueError(f"非法英雄 ID: {hero_id}")
    toml_path = _CONFIG_DIR / "war3" / "jiubing2" / "heroes" / f"{hero_id}.toml"
    if not toml_path.exists():
        raise FileNotFoundError(f"英雄配置不存在: {toml_path}")
    with open(toml_path, "r", encoding="utf-8") as f:
        return f.read()


def import_hero_batch(heroes: list) -> dict:
    """批量导入英雄配置。

    参数 heroes: [{ hero_id, content }, ...]
    返回 { saved: [...], errors: [...] }
    """
    saved = []
    errors = []
    for item in heroes:
        hero_id = (item.get("hero_id") or "").strip()
        content = item.get("content", "")
        try:
            if not _HERO_ID_RE.match(hero_id):
                raise ValueError(f"非法英雄 ID: {hero_id}")
            if not content.strip():
                raise ValueError("配置内容为空")
            tomllib.loads(content)
            toml_path = _CONFIG_DIR / "war3" / "jiubing2" / "heroes" / f"{hero_id}.toml"
            with open(toml_path, "w", encoding="utf-8") as f:
                f.write(content)
            saved.append(hero_id)
        except Exception as ie:
            errors.append(f"{hero_id}: {ie}")
    return {"saved": saved, "errors": errors}


def _prune_running_processes():
    """清理已结束的任务进程。"""
    for task_id, proc in list(_running_processes.items()):
        if proc.poll() is not None:
            del _running_processes[task_id]


def start_task(task_id: str) -> dict:
    """启动任务子进程。

    返回 { ok, pid, log } 或 { ok: False, error, running, pid }。
    """
    if not is_runnable_task(task_id):
        raise FileNotFoundError("未找到可执行的任务脚本")

    _prune_running_processes()
    if task_id in _running_processes:
        proc = _running_processes[task_id]
        if proc.poll() is None:
            return {"ok": False, "error": "该任务正在运行", "running": True, "pid": proc.pid}

    module = f"GameBot.runner.tasks.war3.jiubing2.{task_id}"
    # Web 服务器运行在主环境（3.12），任务子进程必须用 3.8 32位 Python（大漠 COM）
    # 优先从 base.toml [dm].python_path 读取，未配置则自动检测 .venv-dm
    main_py = _WEB_CONFIG.get("dm_python_path", "")
    if not main_py:
        _base_toml = _CONFIG_DIR / "war3" / "jiubing2" / "base.toml"
        if _base_toml.exists():
            try:
                with open(_base_toml, "rb") as f:
                    _base_data = tomllib.load(f)
                main_py = _base_data.get("dm", {}).get("python_path", "")
            except Exception:
                pass
    if main_py:
        _main_py_path = Path(main_py)
        if not _main_py_path.is_absolute():
            _main_py_path = _PROJECT_ROOT / _main_py_path
        main_py = str(_main_py_path)
    else:
        # 未配置则自动检测标准路径
        _dm_py = _PROJECT_ROOT / ".venv-dm" / "Scripts" / "python.exe"
        main_py = str(_dm_py) if _dm_py.exists() else sys.executable
    cmd = [main_py, "-m", module]
    env = os.environ.copy()
    src_path = str(_PROJECT_ROOT / "src")
    old_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{old_pp}" if old_pp else src_path
    log_dir = _PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"web_{task_id.replace('.', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    with open(log_file, "a", encoding="utf-8", errors="replace") as log_fh:
        proc = subprocess.Popen(
            cmd,
            cwd=_PROJECT_ROOT,
            env=env,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    _running_processes[task_id] = proc
    return {"ok": True, "pid": proc.pid, "log": str(log_file)}


def get_running_tasks() -> list:
    """获取正在运行的任务列表。"""
    _prune_running_processes()
    return [{"id": task_id, "pid": proc.pid} for task_id, proc in _running_processes.items()]


# 任务配置 schema（前端据此自动渲染表单）
TASK_SCHEMAS = {
    "patrol_loot": {
        "id": "patrol_loot",
        "name": "刷装备",
        "description": "在可能出现物品掉落的地点设置巡逻点，循环杀怪并自动拾取目标装备。需配置物品栏、待刷装备和巡逻路线。AI 自动检测地面宝箱，OCR 识别物品名称。",
        "sections": [
            {
                "key": "guide",
                "title": "使用说明",
                "content": (
                    "<p><strong>环境要求：</strong></p>"
                    "<ul>"
                    "<li>英雄初始位置在奇异之地裂隙旁或荒漠废墟裂隙旁（根据路线方案选择），脚本执行中，英雄不能死亡</li>"
                    "<li>在物品栏中装备宠物食物并设置快捷键</li>"
                    "<li>储物箱已满或装备数量目标达成就不会再拾取了，脚本进入仅喂食宠物状态</li>"
                    "<li>务必在宠物食物耗尽前查看装备情况，及时保存，按照目前饱和度每分钟约3%下降速度，50个食物大概能用7~8小时</li>"
                    "<li>路线点里的时间根据自己实际运行时杀怪情况来调整，杀得慢就调大</li>"
                    "</ul>"
                    "<p><strong>路线方案：</strong></p>"
                    "<ul>"
                    "<li>英雄强就选择荒漠废墟，否则奇异之地，最好在运行脚本前自己先去试试强度</li>"
                    "<li>推荐满人最高难度下奇异之地路线，掉率更高</li>"
                    "</ul>"
                    "<p><strong>英雄与技能：</strong></p>"
                    "<ul>"
                    "<li>英雄为可选项；选择英雄后可在路线点中配置技能</li>"
                    "<li>未选择英雄或未配置技能时，到达路线点后将使用普通攻击</li>"
                    "</ul>"
                ),
            },
            {
                "key": "hero",
                "title": "选择英雄",
                "help": "点击英雄进行选择或取消选择；选择英雄后可在路线点中配置技能。",
                "fields": [{"key": "hero", "label": "", "type": "hero"}],
            },
            {
                "key": "inventory",
                "title": "物品栏装备",
                "help": "前 5 格可自由设置携带装备和快捷键，第 6 格固定为拾取。",
                "footer": "请确保携带宠物食物，以免宠物饥饿导致逃亡",
                "fields": [
                    {"key": "inventory", "label": "", "type": "inventory"},
                ],
            },
            {
                "key": "desired",
                "title": "待刷装备",
                "help": "勾选需要刷取的装备并设置最大数量。",
                "fields": [
                    {"key": "desired_items", "label": "", "type": "desired_items"},
                ],
            },
            {
                "key": "patrol",
                "title": "巡逻设置",
                "fields": [
                    {"key": "patrol_rounds", "label": "巡逻轮数", "type": "number", "default": 0, "min": 0, "controls": False, "width": "120px", "size": "default", "help": "0 表示无限循环"},
                ],
            },
            {
                "key": "chest",
                "title": "宝箱检测参数",
                "help": "调整宝箱 AI 检测的严格程度，需与训练模型保持一致。",
                "fields": [
                    {"key": "chest.ai_conf", "label": "置信度阈值", "type": "number", "default": 0.5, "min": 0, "max": 1, "step": 0.05, "help": "越高越严格，越低越容易误检"},
                    {"key": "chest.ai_iou", "label": "NMS IoU 阈值", "type": "number", "default": 0.5, "min": 0, "max": 1, "step": 0.05, "help": "重叠大于此值视为同一目标"},
                ],
            },
            {
                "key": "route",
                "title": "路线",
                "help": "选择预设路线方案后自动加载对应路线点，也可在下方手动调整、拖动。",
                "fields": [
                    {"key": "route_scheme", "label": "路线方案", "type": "route_scheme"},
                    {"key": "points", "label": "", "type": "points"},
                ],
            },
        ],
    },
    "others.upgrade_stigmata": {
        "id": "others.upgrade_stigmata",
        "name": "升级圣痕",
        "description": "通过完成城门骚扰任务获取圣痕升级机会来升级圣痕，直到所有词条达标。",
        "sections": [
            {
                "key": "guide",
                "title": "使用说明",
                "content": (
                    "<p><strong>环境要求：</strong></p>"
                    "<ul>"
                    "<li>英雄需在黑石城守卫队长附近接取任务</li>"
                    "<li>任务过程中英雄不能死亡</li>"
                    "</ul>"
                    "<p><strong>圣痕配置：</strong></p>"
                    "<ul>"
                    "<li>上位、核心、中位、下位共 4 个位置，每个位置 3 个词条</li>"
                    "<li>在每行输入形如 <code>2,4,1</code> 的数字，表示该位置 3 个词条分别还需升级的次数（建议加大一点，满了会检测，不会一直升级该位置）</li>"
                    "</ul>"
                    "<p><strong>英雄与技能：</strong></p>"
                    "<ul>"
                    "<li>英雄为可选项；选择英雄后可在路线点中配置技能</li>"
                    "<li>未选择英雄或未配置技能时，沿路线点使用 A+左键 边走边打</li>"
                    "</ul>"
                ),
            },
            {
                "key": "hero",
                "title": "选择英雄",
                "help": "点击英雄进行选择或取消选择；选择英雄后可在路线点中配置技能。",
                "fields": [{"key": "hero", "label": "", "type": "hero"}],
            },
            {
                "key": "inventory",
                "title": "物品栏装备",
                "help": "前 5 格可自由设置携带装备和快捷键，第 6 格固定为拾取。",
                "fields": [{"key": "inventory", "label": "", "type": "inventory"}],
            },
            {
                "key": "stigmata",
                "title": "圣痕待升级配置",
                "help": "",
                "fields": [
                    {"key": "upgrade_config", "label": "", "type": "stigmata_matrix"},
                ],
            },
            {
                "key": "basic",
                "title": "基础设置",
                "fields": [
                    {"key": "clear_nearby_probability", "label": "清理附近物品概率", "type": "number", "unit": "", "default": 0.15, "min": 0, "max": 1, "step": 0.05, "controls": False, "width": "160px", "size": "default", "help": "每个路线点清理英雄附近物品的概率，0 = 禁用"},
                ],
            },
            {
                "key": "route",
                "title": "路线",
                "help": "编辑城门骚扰路线点；选择英雄后可为每个点配置技能。",
                "fields": [
                    {"key": "points", "label": "", "type": "points"},
                ],
            },
        ],
    },
    "others.fishing": {
        "id": "others.fishing",
        "name": "钓鱼",
        "description": "英雄下方必须是水域（推荐米奈希尔灯塔、卡米村复活石下方），三角和圆圈不能被遮挡，抛竿不能抛到陆地上，必须有鱼竿及其快捷键，设置检测参数即可。",
        "sections": [
            {
                "key": "guide",
                "title": "使用说明",
                "content": (
                    "<p><strong>环境要求：</strong></p>"
                    "<ul>"
                    "<li>英雄下方必须是水域（推荐米奈希尔灯塔、卡米村复活石下方），远离npc（中钩区域不能有大片红色）脚本执行中，英雄不能死亡</li>"
                    "<li>三角和圆圈不能被遮挡，抛竿不能抛到陆地上（先站好位置，双击f1，自己手动钓鱼测试一下）</li>"
                    "<li>在物品栏中装备鱼竿并设置快捷键</li>"
                    "</ul>"
                ),
            },
            {
                "key": "inventory",
                "title": "物品栏装备",
                "help": "请确保装备了鱼竿。",
                "fields": [
                    {"key": "inventory", "label": "", "type": "inventory"},
                ],
            },
            {
                "key": "basic",
                "title": "基础设置",
                "fields": [
                    {"key": "max_times", "label": "抛竿次数", "type": "number", "default": 10000, "min": 1, "controls": False, "width": "140px", "size": "default"},
                    {"key": "fishing_interval_time", "label": "钓鱼间隔", "type": "number", "unit": "秒", "default": 1, "min": 0, "step": 0.5, "controls": False, "width": "140px", "size": "default", "help": "两次抛竿之间的等待时间"},
                    {"key": "clear_nearby_probability", "label": "清理附近物品概率", "type": "number", "unit": "", "default": 0.15, "min": 0, "max": 1, "step": 0.05, "controls": False, "width": "160px", "size": "default", "help": "每次收竿后清理英雄附近物品的概率，0 = 禁用"},
                ],
            },
            {
                "key": "hook_detect",
                "title": "中钩检测",
                "help": "配置红色三角方块（中钩标志）找图参数。",
                "fields": [
                    {"key": "hook_coords", "label": "抛竿目标位置", "type": "coords", "help": "鱼钩的窗口坐标 [x, y]"},
                    {"key": "check.hook_sim", "label": "相似度", "type": "number", "default": 0.9, "min": 0, "max": 1, "step": 0.05, "controls": False, "width": "140px", "size": "default", "help": "相似度阈值，越低越早检测到但可能误触，最大不超过1"},
                    {"key": "check.status_area_coords", "label": "检测区域", "type": "coords", "help": "包含所有三角形和圆圈的区域坐标[x1, y1, x2, y2]，范围越小检测越快，但所有三角和圆圈必须包含在内"},
                    {"key": "check.hook_timeout", "label": "等待超时", "type": "number", "unit": "秒", "default": 15, "min": 1, "step": 1, "controls": False, "width": "140px", "size": "default", "help": "一次钓鱼等待中钩的超时时间"},
                    {"key": "is_test_check", "label": "启动前测试检测区域", "type": "switch", "default": False, "help": "开启后正式钓鱼前会框选检测区域以便确认英雄位置是否正确"},
                ],
            },
            {
                "key": "predict",
                "title": "预判收竿",
                "help": "通过填充循环周期推算下次红色出现时刻，提前按键收竿。",
                "fields": [
                    {"key": "check.retract_lead_time", "label": "提前量", "type": "number", "unit": "秒", "default": 0.1, "min": 0, "step": 0.05, "controls": False, "width": "140px", "size": "default", "help": "收竿偏晚则调大，收竿过早则调小"},
                ],
            },
        ],
    },
    "daily_reputation": {
        "id": "daily_reputation",
        "name": "每日声望",
        "description": "完成黑石城和/或森之城的每日声望任务。黑石城通过城门骚扰任务（每次+5声望，上限150），森之城通过迅猛野兽任务（每次+10声望，上限150）。可选择只做其中一个或都做。",
        "sections": [
            {
                "key": "guide",
                "title": "使用说明",
                "content": (
                    "<p><strong>环境要求：</strong></p>"
                    "<ul>"
                    "<li>英雄需装备传送卷（物品栏第6格之前的某格），用于从黑石城转场至森之城</li>"
                    "<li>做黑石城声望时英雄需在黑石城守卫队长附近</li>"
                    "<li>任务过程中英雄不能死亡</li>"
                    "</ul>"
                    "<p><strong>声望目标说明：</strong></p>"
                    "<ul>"
                    "<li><strong>黑石城 + 森之城：</strong>先完成黑石城声望，再用传送卷转场至森之城完成森之城声望</li>"
                    "<li><strong>仅黑石城：</strong>只完成黑石城声望，英雄初始位置在任务npc附近</li>"
                    "<li><strong>仅森之城：</strong>先用传送卷转场至森之城，再完成森之城声望</li>"
                    "</ul>"
                    "<p><strong>英雄与技能：</strong></p>"
                    "<ul>"
                    "<li>英雄为可选项；选择英雄后可在路线点中配置技能</li>"
                    "<li>未选择英雄或未配置技能时，沿路线点使用 A+左键 边走边打</li>"
                    "</ul>"
                ),
            },
            {
                "key": "hero",
                "title": "选择英雄",
                "help": "点击英雄进行选择或取消选择；选择英雄后可在路线点中配置技能。",
                "fields": [{"key": "hero", "label": "", "type": "hero"}],
            },
            {
                "key": "inventory",
                "title": "物品栏装备",
                "help": "前 5 格可自由设置携带装备和快捷键，第 6 格固定为拾取。第 5 格默认放置传送卷轴用于转场至森之城。",
                "showIf": {"field": "enable_forest", "value": True},
                "fields": [
                    {"key": "inventory", "label": "", "type": "inventory"},
                ],
            },
            {
                "key": "target",
                "title": "声望目标",
                "fields": [
                    {"key": "enable_blackstone", "label": "黑石城声望", "type": "checkbox", "default": True, "help": "勾选则执行黑石城城门骚扰任务（每次+5声望，上限150）"},
                    {"key": "enable_forest", "label": "森之城声望", "type": "checkbox", "default": True, "help": "勾选则执行森之城迅猛野兽任务（每次+10声望，上限150）"},
                ],
            },
            {
                "key": "blackstone_route",
                "title": "黑石城路线",
                "help": "城门骚扰任务的路线点，末点为守卫队长附近（交/接任务）。",
                "showIf": {"field": "enable_blackstone", "value": True},
                "fields": [
                    {"key": "blackstone_points", "label": "", "type": "points"},
                ],
            },
            {
                "key": "forest_route",
                "title": "森之城路线",
                "help": "迅猛野兽任务的路线点，末点为月之女祭司狄安娜附近（交/接任务）。",
                "showIf": {"field": "enable_forest", "value": True},
                "fields": [
                    {"key": "forest_points", "label": "", "type": "points"},
                ],
            },
        ],
    },
    "achievements.personal": {
        "id": "achievements.personal",
        "name": "个人任务成就",
        "description": "反复完成卡米村村民杰菲特的多个任务（毒蛇、蛇蛋、小炎蛇），同时接取后走共享路线，依次提交，每次提交算 1 次。英雄和物品栏可在本页配置，未选择时继承自原子任务依赖链。注意：小炎蛇有前置要求——本局必须完成至少一次毒蛇。",
        "sections": [
            {
                "key": "guide",
                "title": "使用说明",
                "content": (
                    "<p><strong>环境要求：</strong></p>"
                    "<ul>"
                    "<li>英雄初始位置在npc左侧附近能接取到位置的地方，脚本执行中，英雄不能死亡</li>"
                    "<li>别学如辉耀等被动aoe技能，容易提前烫死怪</li>"
                    "</ul>"
                ),
            },
            {
                "key": "hero",
                "title": "选择英雄",
                "help": "点击英雄进行选择或取消选择；选择英雄后可在路线点中配置技能。",
                "fields": [{"key": "hero", "label": "", "type": "hero"}],
            },
            {
                "key": "inventory",
                "title": "物品栏装备",
                "help": "前 5 格可自由设置携带装备和快捷键，第 6 格固定为拾取。",
                "fields": [{"key": "inventory", "label": "", "type": "inventory"}],
            },
            {
                "key": "task_settings",
                "title": "任务设置",
                "fields": [
                    {"key": "task_times", "label": "目标完成次数", "type": "number", "default": 4150, "min": 1, "controls": False, "width": "160px", "size": "default", "help": "需要完成多少次个人任务"},
                    {"key": "loop_interval_time", "label": "循环间隔", "type": "number", "unit": "秒", "default": 1.5, "min": 0, "step": 0.5, "controls": False, "width": "120px", "size": "default", "help": "两次任务之间的等待时间"},
                    {"key": "clear_nearby_probability", "label": "清理附近物品概率", "type": "number", "unit": "", "default": 0.15, "min": 0, "max": 1, "step": 0.05, "controls": False, "width": "160px", "size": "default", "help": "每个路线点清理英雄附近物品的概率，0 = 禁用"},
                ],
            },
            {
                "key": "points",
                "title": "路线",
                "help": "可以设置原子任务专属路线点，毒蛇和蛇蛋可以共用一条路线，小炎蛇单独一条。无任务标记的点始终走。",
                "fields": [
                    {"key": "points", "label": "", "type": "points", "taskOptions": [
                        {"value": "venomous_snake", "label": "毒蛇"},
                        {"value": "snake_egg", "label": "蛇蛋"},
                        {"value": "little_flame_snake", "label": "小炎蛇（LV4）"},
                    ]},
                ],
            },
        ],
    },
}

# 把“使用说明”章节统一放到最后面
for _schema in TASK_SCHEMAS.values():
    _sections = _schema["sections"]
    for _i, _section in enumerate(_sections):
        if _section.get("key") == "guide":
            _sections.append(_sections.pop(_i))
            break


def get_task_schema(task_id: str) -> Optional[dict]:
    """获取任务的表单 schema，附带默认值和配置说明。"""
    short = task_id.split(".")[-1]
    schema = TASK_SCHEMAS.get(task_id) or TASK_SCHEMAS.get(short)
    if schema:
        resp = copy.deepcopy(schema)
        resp["defaults"] = load_task_defaults(task_id)
        return resp
    return None
