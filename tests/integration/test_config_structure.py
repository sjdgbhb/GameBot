"""真实配置文件结构验证集成测试。

验证 src/GameBot/config/data/ 下的所有 TOML 配置文件：
- TOML 语法合法（可被 tomllib 解析）
- 任务 TOML 的 _find_task_section() 能正确提取 name 字段
- extends 声明的继承路径都有对应文件存在
- 英雄 TOML 的 inventory 格式合法
- base.toml 含 items 定义和 command 段
"""

import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

pytestmark = [pytest.mark.integration]

# 项目根目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_DIR = _PROJECT_ROOT / "src" / "GameBot" / "config" / "data"
_JIUBING2_DIR = _CONFIG_DIR / "war3" / "jiubing2"
_TASKS_DIR = _JIUBING2_DIR / "tasks"
_HEROES_DIR = _JIUBING2_DIR / "heroes"
_SCENES_DIR = _JIUBING2_DIR / "scenes"


# ── 辅助函数（复制自 services.py，避免导入 web 模块触发 FastAPI 依赖） ──


def _find_task_section(data: dict) -> dict:
    """在 TOML 的 [this] 段中找到任务节点。"""
    return data.get("this", {}) if isinstance(data.get("this"), dict) else {}


def _resolve_dependency_path(dep: str) -> Path | None:
    """将依赖名（如 war3.jiubing2.heroes.mk）解析为配置文件路径。

    支持三种形式：
    - war3.jiubing2.heroes.mk → war3/jiubing2/heroes/mk.toml
    - war3.jiubing2 → war3/jiubing2/jiubing2.toml 或 war3/jiubing2/base.toml
    - base → base.toml
    """
    parts = dep.split(".")
    # 尝试 parts/path/to/file.toml
    candidate = _CONFIG_DIR.joinpath(*parts).with_suffix(".toml")
    if candidate.exists():
        return candidate
    # 尝试目录下的 base.toml（如 war3.jiubing2 → war3/jiubing2/base.toml）
    candidate = _CONFIG_DIR.joinpath(*parts, "base").with_suffix(".toml")
    if candidate.exists():
        return candidate
    # 尝试目录下的 index.toml
    candidate = _CONFIG_DIR.joinpath(*parts, "index").with_suffix(".toml")
    if candidate.exists():
        return candidate
    # 尝试目录本身存在（无 TOML 但有子目录，如 war3 → war3/ 目录）
    candidate_dir = _CONFIG_DIR.joinpath(*parts)
    if candidate_dir.is_dir():
        return candidate_dir
    return None


# ── TOML 合法性 ──


class TestTomlValidity:
    """所有 TOML 配置文件应能被 tomllib 正确解析。"""

    @staticmethod
    def _all_toml_files() -> list:
        """收集 config/data/ 下所有 .toml 文件。"""
        return sorted(_CONFIG_DIR.rglob("*.toml"))

    def test_all_toml_files_parseable(self):
        """所有 TOML 文件应能被 tomllib 解析，无语法错误。"""
        files = self._all_toml_files()
        assert len(files) > 0, "config/data/ 下应存在 TOML 配置文件"
        errors = []
        for toml_path in files:
            try:
                with open(toml_path, "rb") as f:
                    tomllib.load(f)
            except Exception as e:
                errors.append(f"{toml_path.relative_to(_CONFIG_DIR)}: {e}")
        assert not errors, "以下 TOML 文件解析失败:\n" + "\n".join(errors)

    def test_base_toml_exists(self):
        """jiubing2/jiubing2.toml 应存在且可解析。"""
        base_path = _JIUBING2_DIR / "jiubing2.toml"
        assert base_path.exists(), "war3/jiubing2/jiubing2.toml 应存在"
        with open(base_path, "rb") as f:
            data = tomllib.load(f)
        assert isinstance(data, dict)

    def test_root_base_toml_exists(self):
        """根 base.toml 应存在且含 [dm] 段。"""
        root_base = _CONFIG_DIR / "base.toml"
        assert root_base.exists(), "config/data/base.toml 应存在"
        with open(root_base, "rb") as f:
            data = tomllib.load(f)
        assert "dm" in data, "base.toml 应含 [dm] 段"


# ── 任务 TOML 结构验证 ──


class TestTaskTomlStructure:
    """所有任务 TOML 应含 name 字段且 extends 路径存在。"""

    @staticmethod
    def _all_task_tomls() -> list:
        """收集 tasks/ 下所有 .toml 文件。"""
        return sorted(_TASKS_DIR.rglob("*.toml"))

    def test_all_task_tomls_have_name(self):
        """每个任务 TOML 的 _find_task_section 应返回含 name 的字典。"""
        files = self._all_task_tomls()
        assert len(files) >= 10, f"tasks/ 下应至少有 10 个 TOML 文件，实际 {len(files)}"
        missing = []
        for toml_path in files:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
            section = _find_task_section(data)
            if not isinstance(section, dict) or "name" not in section:
                rel = toml_path.relative_to(_TASKS_DIR)
                missing.append(str(rel))
        assert not missing, f"以下任务 TOML 缺少 name 字段: {missing}"

    def test_all_task_tomls_have_extends(self):
        """每个任务 TOML 应声明 extends。"""
        files = self._all_task_tomls()
        missing = []
        for toml_path in files:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
            deps = data.get("extends")
            if not isinstance(deps, list) or len(deps) == 0:
                rel = toml_path.relative_to(_TASKS_DIR)
                missing.append(str(rel))
        assert not missing, f"以下任务 TOML 缺少 extends: {missing}"

    def test_task_extends_resolve_to_files(self):
        """每个任务声明的 extends 路径都应存在对应文件。"""
        files = self._all_task_tomls()
        missing = []
        for toml_path in files:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
            deps = data.get("extends", [])
            for dep in deps:
                if not isinstance(dep, str):
                    continue
                resolved = _resolve_dependency_path(dep)
                if resolved is None:
                    rel = toml_path.relative_to(_TASKS_DIR)
                    missing.append(f"{rel} -> {dep} (未找到对应文件)")
        assert not missing, "以下依赖路径未找到对应文件:\n" + "\n".join(missing)

    def test_task_toml_ids_match_file_paths(self):
        """任务 TOML 的相对路径应与顶层 name 一致。"""
        files = self._all_task_tomls()
        for toml_path in files:
            rel = toml_path.relative_to(_TASKS_DIR).with_suffix("")
            task_id = ".".join(rel.parts)
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
            expected_name = f"war3.jiubing2.tasks.{task_id}"
            assert data.get("name") == expected_name, f"{toml_path.name}: name 应为 '{expected_name}'"


# ── 英雄 TOML 结构验证 ──


class TestHeroTomlStructure:
    """所有英雄 TOML 应含 [hero] 段且 inventory 格式合法。"""

    @staticmethod
    def _all_hero_tomls() -> list:
        return sorted(_HEROES_DIR.glob("*.toml"))

    def test_all_hero_tomls_have_hero_section(self):
        """每个英雄 TOML 应含 [hero] 段。"""
        files = self._all_hero_tomls()
        assert len(files) >= 10, f"heroes/ 下应至少有 10 个英雄，实际 {len(files)}"
        missing = []
        for toml_path in files:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
            if "hero" not in data or not isinstance(data["hero"], dict):
                missing.append(toml_path.name)
        assert not missing, f"以下英雄 TOML 缺少 [hero] 段: {missing}"

    def test_all_heroes_have_name(self):
        """每个英雄应含 name 字段。"""
        files = self._all_hero_tomls()
        missing = []
        for toml_path in files:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
            hero = data.get("hero", {})
            if not hero.get("name"):
                missing.append(toml_path.name)
        assert not missing, f"以下英雄 TOML 缺少 hero.name: {missing}"

    def test_all_heroes_have_floor_key(self):
        """每个英雄应含 floor_key 字段。"""
        files = self._all_hero_tomls()
        missing = []
        for toml_path in files:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
            hero = data.get("hero", {})
            if not hero.get("floor_key"):
                missing.append(toml_path.name)
        assert not missing, f"以下英雄 TOML 缺少 hero.floor_key: {missing}"

    def test_hero_inventory_format_valid(self):
        """英雄 inventory 中每项应含 slot 和 item_id / item（配置层会解析 item 为 item_id）。"""
        files = self._all_hero_tomls()
        invalid = []
        for toml_path in files:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
            inventory = data.get("hero", {}).get("inventory", [])
            if not inventory:
                continue
            for item in inventory:
                if not isinstance(item, dict):
                    invalid.append(f"{toml_path.name}: inventory 项非 dict")
                elif "slot" not in item or ("item_id" not in item and "item" not in item):
                    invalid.append(f"{toml_path.name}: inventory 项缺少 slot 或 item_id/item")
        assert not invalid, "以下英雄 inventory 格式不合法:\n" + "\n".join(invalid)

    def test_hero_extends_include_jiubing2(self):
        """每个英雄应声明 extends 含 war3.jiubing2。"""
        files = self._all_hero_tomls()
        missing = []
        for toml_path in files:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
            deps = data.get("extends", [])
            if "war3.jiubing2" not in deps:
                missing.append(toml_path.name)
        assert not missing, f"以下英雄缺少 war3.jiubing2 extends: {missing}"


# ── jiubing2.toml 结构验证 ──


class TestBaseTomlStructure:
    """jiubing2/jiubing2.toml 应含必需的配置段。"""

    def test_base_has_command_section(self):
        """jiubing2.toml 应含 [command] 段。"""
        with open(_JIUBING2_DIR / "jiubing2.toml", "rb") as f:
            data = tomllib.load(f)
        assert "command" in data, "jiubing2.toml 应含 [command] 段"
        cmd = data["command"]
        assert isinstance(cmd, dict)
        assert "clear_nearby" in cmd, "command 应含 clear_nearby"

    def test_base_has_items_section(self):
        """jiubing2.toml 应含 [items] 段（物品定义表）。"""
        with open(_JIUBING2_DIR / "jiubing2.toml", "rb") as f:
            data = tomllib.load(f)
        assert "items" in data, "jiubing2.toml 应含 [items] 段"
        items = data["items"]
        assert isinstance(items, list) and len(items) > 0, "items 应为非空列表"
        for item in items:
            assert "id" in item and "name" in item, f"物品定义缺少 id/name: {item}"

    def test_base_has_game_section(self):
        """jiubing2.toml 应含 [game] 段。"""
        with open(_JIUBING2_DIR / "jiubing2.toml", "rb") as f:
            data = tomllib.load(f)
        assert "game" in data, "jiubing2.toml 应含 [game] 段"
        game = data["game"]
        assert isinstance(game, dict)
        assert "load_war3_time" in game, "game 应含 load_war3_time"


# ── 场景 TOML 结构验证 ──


class TestSceneTomlStructure:
    """场景 TOML 应可解析且含基本结构。"""

    def test_all_scene_tomls_parseable(self):
        """所有场景 TOML 应可解析。"""
        files = sorted(_SCENES_DIR.glob("*.toml"))
        assert len(files) >= 3, f"scenes/ 下应至少有 3 个场景，实际 {len(files)}"
        for toml_path in files:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
            assert isinstance(data, dict), f"{toml_path.name} 解析结果应为 dict"


# ── 无尽任务优化配置加载验证 ──


class TestEndlessOptimizationConfig:
    """无尽任务优化新增配置段加载验证。"""

    # I-01: kk.create_room 配置可加载
    def test_kk_create_room_config_loads(self):
        """kk.toml 中 [kk.create_room] 配置段应可加载且含必需字段。"""
        kk_path = _CONFIG_DIR / "kk.toml"
        assert kk_path.exists(), "kk.toml 应存在"
        with open(kk_path, "rb") as f:
            data = tomllib.load(f)
        kk = data.get("this", {})
        create_room = kk.get("create_room", {})
        assert "dialog_window_size" in create_room, "kk.create_room 应含 dialog_window_size"
        assert "password_input_coords" in create_room, "kk.create_room 应含 password_input_coords"
        assert "confirm_create_coords" in create_room, "kk.create_room 应含 confirm_create_coords"
        assert "password" in create_room, "kk.create_room 应含 password"

    # I-04: kk.main 配置可加载
    def test_kk_main_config_loads(self):
        """kk.toml 中 [kk.main] 配置段应可加载。"""
        kk_path = _CONFIG_DIR / "kk.toml"
        with open(kk_path, "rb") as f:
            data = tomllib.load(f)
        kk = data.get("this", {})
        main = kk.get("main", {})
        assert "window_size" in main, "kk.main 应含 window_size"
        assert "search_input_coords" in main, "kk.main 应含 search_input_coords"
        assert "map_result_ocr_area_coords" in main, "kk.main 应含 map_result_ocr_area_coords"
        assert "profile_icon_coords" in main, "kk.main 应含 profile_icon_coords"
        assert "username_area_coords" in main, "kk.main 应含 username_area_coords"

    # I-01b: kk.room 配置可加载
    def test_kk_room_config_loads(self):
        """kk.toml 中 [kk.room] 配置段应可加载（房间不再 OCR 玩家名）。"""
        kk_path = _CONFIG_DIR / "kk.toml"
        with open(kk_path, "rb") as f:
            data = tomllib.load(f)
        kk = data.get("this", {})
        room = kk.get("room", {})
        assert "window_size" in room, "kk.room 应含 window_size"
        assert "room_id_ocr_area_coords" in room, "kk.room 应含 room_id_ocr_area_coords"

    # I-02: war3.multi_instance 配置可加载
    def test_war3_multi_instance_config_loads(self):
        """war3.toml 中 [war3.multi_instance] 配置段应可加载。"""
        war3_path = _CONFIG_DIR / "war3" / "war3.toml"
        assert war3_path.exists(), "war3/war3.toml 应存在"
        with open(war3_path, "rb") as f:
            data = tomllib.load(f)
        war3 = data.get("this", {})
        multi = war3.get("multi_instance", {})
        loading_page = multi.get("loading_page", {})
        assert "area_coords" in loading_page, "war3.multi_instance.loading_page 应含 area_coords"

    # I-03: endless.target_player 可读取
    def test_endless_target_player_inherits(self):
        """endless.toml 中 target_player 配置项应可读取。"""
        endless_path = _TASKS_DIR / "endless" / "endless.toml"
        assert endless_path.exists(), "endless/endless.toml 应存在"
        with open(endless_path, "rb") as f:
            data = tomllib.load(f)
        section = _find_task_section(data)
        assert "target_player" in section, "endless.toml 任务配置应含 target_player"


# ── 任务配置闭包完整性（load_task 真实加载） ──


class TestTaskConfigClosure:
    """经 load_task 加载的任务配置闭包完整性验证。

    防止「TOML 语法/文件都存在，但合并后缺运行时依赖节点」类问题
    （如 ForestReputationTask 需要 scenes.menethil.teleport.forest_waygate，
    依赖未声明时运行到转场才抛 KeyError）。
    """

    # 已知运行时依赖的必备节点（合并后的点分路径）
    _REQUIRED_NODES = {
        "war3.jiubing2.tasks.reputation.daily_reputation": [
            "war3.jiubing2.scenes.blackstone_city.npcs.guard_captain",
            "war3.jiubing2.scenes.forest_city.npcs.diana",
            "war3.jiubing2.scenes.menethil.teleport.forest_waygate",
        ],
        "war3.jiubing2.tasks.festival.ingame_special": [
            "war3.jiubing2.scenes.menethil.teleport.forest_waygate",
            "war3.jiubing2.tasks.reputation.daily_reputation",
            "war3.jiubing2.tasks.others.fishing",
        ],
    }

    @staticmethod
    def _task_name(toml_path: Path) -> str:
        """TOML 路径 → 配置名（tasks/atomic/foo.toml → war3.jiubing2.tasks.atomic.foo）。"""
        rel = toml_path.relative_to(_JIUBING2_DIR).with_suffix("")
        return "war3.jiubing2." + ".".join(rel.parts)

    @staticmethod
    def _dig(cfg: dict, dotted: str):
        """按点分路径取值，缺失返回 None。"""
        node = cfg
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def test_all_tasks_load_without_error(self):
        """每个任务 TOML 应能通过 load_task 完整加载，且合并后含任务节点和 name。"""
        from GameBot.config import config

        errors = []
        for toml_path in sorted(_TASKS_DIR.rglob("*.toml")):
            name = self._task_name(toml_path)
            try:
                cfg = config.load_task(name)
            except Exception as e:
                errors.append(f"{name}: {e}")
                continue
            node = self._dig(cfg, name)
            if not isinstance(node, dict) or not node.get("name"):
                errors.append(f"{name}: 合并后缺少任务节点或 name")
        assert not errors, "以下任务加载失败或缺少任务节点:\n" + "\n".join(errors)

    def test_hero_inventory_slots_injected(self):
        """每个任务闭包应将 kk.inventory_slots 注入 hero（get_inventory_hotkey 依赖）。"""
        from GameBot.config import config

        missing = []
        for toml_path in sorted(_TASKS_DIR.rglob("*.toml")):
            name = self._task_name(toml_path)
            cfg = config.load_task(name)
            if not cfg.get("hero", {}).get("inventory_slots"):
                missing.append(name)
        assert not missing, "以下任务闭包缺少 hero.inventory_slots:\n" + "\n".join(missing)

    def test_required_runtime_nodes(self):
        """关键任务闭包应含运行时必备节点（防 menethil.teleport 缺失类 bug）。"""
        from GameBot.config import config

        errors = []
        for task_name, nodes in self._REQUIRED_NODES.items():
            cfg = config.load_task(task_name)
            for node_path in nodes:
                if self._dig(cfg, node_path) is None:
                    errors.append(f"{task_name} 缺少 {node_path}")
        assert not errors, "以下任务闭包缺少必备节点:\n" + "\n".join(errors)
