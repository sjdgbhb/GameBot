"""Web API 单元测试（pytest 风格）——使用 FastAPI TestClient 测试所有路由。

覆盖范围：
- GET /api/init
- POST /api/save
- GET /api/schema/{task_id}
- GET /api/hero_export/{hero_id}
- POST /api/save_hero_inventory
- POST /api/hero_import_batch
- POST /api/start/{task_id}
- GET /api/running
- services 层辅助函数
"""

from unittest.mock import MagicMock

import pytest

from GameBot.web.api import services

pytestmark = [pytest.mark.web, pytest.mark.unit]


class TestInitEndpoint:
    """GET /api/init 接口测试。"""

    def test_init_returns_all_data(self, web_client, monkeypatch):
        """init 接口应返回任务、英雄、物品、可刷物品、指令、用户配置。"""
        monkeypatch.setattr(
            services,
            "load_tasks",
            lambda: [
                {
                    "id": "others.fishing",
                    "name": "钓鱼",
                    "short_id": "fishing",
                    "category": "others",
                    "icon": "🎣",
                    "description": "",
                    "configurable": False,
                },
            ],
        )
        monkeypatch.setattr(
            services,
            "load_heroes",
            lambda: [
                {"id": "paladin", "name": "圣骑士", "floor_key": "P", "inventory": [], "skills": []},
            ],
        )
        monkeypatch.setattr(services, "load_items", lambda: [{"id": 1, "name": "铁剑"}])
        monkeypatch.setattr(services, "load_farmable_items", lambda: ["铁剑", "银甲"])
        monkeypatch.setattr(services, "load_commands", lambda: [{"key": "attack", "cmd": "a"}])
        monkeypatch.setattr(services, "load_user_configs", lambda: {"hero": "paladin"})

        resp = web_client.get("/api/init")
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["id"] == "others.fishing"
        assert len(data["heroes"]) == 1
        assert data["heroes"][0]["id"] == "paladin"
        assert len(data["items"]) == 1
        assert data["farmable_items"] == ["铁剑", "银甲"]
        assert len(data["commands"]) == 1
        assert data["configs"] == {"hero": "paladin"}

    def test_init_empty_data(self, web_client, monkeypatch):
        """空数据时 init 应返回空列表/空字典，不报错。"""
        for name in ("load_tasks", "load_heroes", "load_items", "load_farmable_items", "load_commands"):
            monkeypatch.setattr(services, name, lambda: [])
        monkeypatch.setattr(services, "load_user_configs", lambda: {})

        resp = web_client.get("/api/init")
        assert resp.status_code == 200
        data = resp.json()

        assert data["tasks"] == []
        assert data["heroes"] == []
        assert data["items"] == []
        assert data["farmable_items"] == []
        assert data["commands"] == []
        assert data["configs"] == {}


class TestSaveConfigEndpoint:
    """POST /api/save 接口测试。"""

    def test_save_config_success(self, web_client, monkeypatch):
        """正常保存用户配置应返回 ok=True。"""
        saved = []

        def _fake_save(data):
            saved.append(data)

        monkeypatch.setattr(services, "save_user_configs", _fake_save)

        resp = web_client.post("/api/save", json={"configs": {"hero": "paladin"}})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_save_config_failure(self, web_client, monkeypatch):
        """保存失败应返回 ok=False 和错误信息。"""

        def _raise(_):
            raise IOError("磁盘已满")

        monkeypatch.setattr(services, "save_user_configs", _raise)

        resp = web_client.post("/api/save", json={"configs": {"hero": "paladin"}})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert "磁盘已满" in data["error"]


class TestSchemaEndpoint:
    """GET /api/schema/{task_id} 接口测试。"""

    def test_schema_found(self, web_client, monkeypatch):
        """存在的任务 schema 应返回完整结构。"""
        monkeypatch.setattr(
            services,
            "get_task_schema",
            lambda _: {
                "id": "patrol_loot",
                "name": "刷装备",
                "description": "巡逻刷装备",
                "sections": [{"key": "hero", "title": "选择英雄", "fields": []}],
                "defaults": {"hero": "paladin"},
            },
        )

        resp = web_client.get("/api/schema/patrol_loot")
        assert resp.status_code == 200
        data = resp.json()

        assert data["id"] == "patrol_loot"
        assert data["name"] == "刷装备"
        assert "sections" in data
        assert "defaults" in data

    def test_schema_not_found(self, web_client, monkeypatch):
        """不存在的任务 schema 应返回 404。"""
        monkeypatch.setattr(services, "get_task_schema", lambda _: None)

        resp = web_client.get("/api/schema/nonexistent_task")
        assert resp.status_code == 404


class TestHeroExportEndpoint:
    """GET /api/hero_export/{hero_id} 接口测试。"""

    def test_export_hero_success(self, web_client, monkeypatch):
        """正常导出英雄配置应返回 TOML 文本。"""
        monkeypatch.setattr(
            services, "export_hero_config", lambda _: '[hero]\ninventory = [\n  {slot = 0, item_id = 1},\n]\n'
        )

        resp = web_client.get("/api/hero_export/paladin")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers.get("content-type", "")
        assert "inventory = [" in resp.text

    def test_export_hero_invalid_id(self, web_client, monkeypatch):
        """非法英雄 ID 应返回 400。"""

        def _raise(_):
            raise ValueError("非法 ID")

        monkeypatch.setattr(services, "export_hero_config", _raise)

        resp = web_client.get("/api/hero_export/bad;id")
        assert resp.status_code == 400

    def test_export_hero_not_found(self, web_client, monkeypatch):
        """不存在的英雄应返回 404。"""

        def _raise(_):
            raise FileNotFoundError("不存在")

        monkeypatch.setattr(services, "export_hero_config", _raise)

        resp = web_client.get("/api/hero_export/ghost_hero")
        assert resp.status_code == 404


class TestSaveHeroInventoryEndpoint:
    """POST /api/save_hero_inventory 接口测试。"""

    def test_save_inventory_success(self, web_client, monkeypatch):
        """正常保存物品栏应返回 ok=True。"""
        saved = []

        def _fake_save(hero_id, inventory):
            saved.append((hero_id, inventory))

        monkeypatch.setattr(services, "save_hero_inventory", _fake_save)

        resp = web_client.post(
            "/api/save_hero_inventory",
            json={
                "hero_id": "paladin",
                "inventory": [{"slot": 0, "item_id": 1}],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_save_inventory_failure(self, web_client, monkeypatch):
        """保存失败应返回 ok=False。"""

        def _raise(_, __):
            raise ValueError("非法 ID")

        monkeypatch.setattr(services, "save_hero_inventory", _raise)

        resp = web_client.post(
            "/api/save_hero_inventory",
            json={
                "hero_id": "bad/id",
                "inventory": [],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is False


class TestHeroImportBatchEndpoint:
    """POST /api/hero_import_batch 接口测试。"""

    def test_import_batch_success(self, web_client, monkeypatch):
        """批量导入全部成功应返回 ok=True。"""
        monkeypatch.setattr(
            services,
            "import_hero_batch",
            lambda _: {
                "saved": ["hero_a", "hero_b"],
                "errors": [],
            },
        )

        resp = web_client.post(
            "/api/hero_import_batch",
            json={
                "heroes": [
                    {"hero_id": "hero_a", "content": "[hero]\nname = 'A'\n"},
                    {"hero_id": "hero_b", "content": "[hero]\nname = 'B'\n"},
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["saved"]) == 2
        assert data["errors"] == []

    def test_import_batch_partial_failure(self, web_client, monkeypatch):
        """部分导入失败应返回 ok=False 和错误列表。"""
        monkeypatch.setattr(
            services,
            "import_hero_batch",
            lambda _: {
                "saved": ["hero_a"],
                "errors": ["hero_b: TOML 格式错误"],
            },
        )

        resp = web_client.post(
            "/api/hero_import_batch",
            json={
                "heroes": [
                    {"hero_id": "hero_a", "content": "[hero]\nname = 'A'\n"},
                    {"hero_id": "hero_b", "content": "invalid toml"},
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert len(data["errors"]) == 1

    def test_import_batch_empty_list(self, web_client):
        """空列表应返回 ok=False。"""
        resp = web_client.post("/api/hero_import_batch", json={"heroes": []})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert "为空" in data["errors"][0]


class TestTaskStartEndpoint:
    """POST /api/start/{task_id} 接口测试。"""

    def test_start_task_success(self, web_client, monkeypatch):
        """正常启动任务应返回 ok=True 和 pid。"""
        monkeypatch.setattr(services, "start_task", lambda _: {"ok": True, "pid": 12345, "log": "/tmp/log.log"})

        resp = web_client.post("/api/start/others.fishing")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["pid"] == 12345

    def test_start_task_not_found(self, web_client, monkeypatch):
        """不存在的任务应返回 404。"""

        def _raise(_):
            raise FileNotFoundError("未找到")

        monkeypatch.setattr(services, "start_task", _raise)

        resp = web_client.post("/api/start/nonexistent.task")
        assert resp.status_code == 404

    def test_start_task_error(self, web_client, monkeypatch):
        """启动异常应返回 ok=False 和错误信息。"""

        def _raise(_):
            raise RuntimeError("启动失败")

        monkeypatch.setattr(services, "start_task", _raise)

        resp = web_client.post("/api/start/others.fishing")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert "启动失败" in data["error"]


class TestRunningTasksEndpoint:
    """GET /api/running 接口测试。"""

    def test_running_empty(self, web_client, monkeypatch):
        """无运行中任务应返回空列表。"""
        monkeypatch.setattr(services, "get_running_tasks", lambda: [])

        resp = web_client.get("/api/running")
        assert resp.status_code == 200
        assert resp.json()["tasks"] == []

    def test_running_with_tasks(self, web_client, monkeypatch):
        """有运行中任务应返回任务列表。"""
        monkeypatch.setattr(services, "get_running_tasks", lambda: [{"id": "others.fishing", "pid": 12345}])

        resp = web_client.get("/api/running")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["id"] == "others.fishing"
        assert data["tasks"][0]["pid"] == 12345


class TestServicesHelpers:
    """services 层纯函数测试（不经过 HTTP 层）。"""

    def test_task_icon_short_id_mapping(self):
        """短 ID 映射应优先于分类映射。"""
        from GameBot.web.api.services import _task_icon

        assert _task_icon("others.fishing") == "🎣"
        assert _task_icon("others.patrol_loot") == "⚔"
        assert _task_icon("endless.endless_single") == "∞"

    def test_task_icon_category_fallback(self):
        """无特殊映射时按分类返回图标。"""
        from GameBot.web.api.services import _task_icon

        assert _task_icon("reputation.daily_reputation") == "🏅"
        assert _task_icon("achievements.personal") == "🏆"
        assert _task_icon("atomic.blackstone_gate_harassment") == "⚡"

    def test_task_icon_unknown_default(self):
        """未知分类应返回默认图标。"""
        from GameBot.web.api.services import _task_icon

        assert _task_icon("unknown.task") == "📜"

    def test_is_runnable_task_valid_id(self):
        """合法任务 ID 格式应通过正则校验。"""
        from GameBot.web.api.services import is_runnable_task

        assert is_runnable_task("others.fishing") is True

    def test_is_runnable_task_invalid_id(self):
        """非法字符的任务 ID 应返回 False。"""
        from GameBot.web.api.services import is_runnable_task

        assert is_runnable_task("../../etc/passwd") is False
        assert is_runnable_task("task with spaces") is False
        assert is_runnable_task("") is False

    def test_find_task_section_nested(self):
        """_find_task_section 应深入嵌套命名空间找到含 name 的节点。"""
        from GameBot.web.api.services import _find_task_section

        data = {"this": {"name": "钓鱼"}}
        result = _find_task_section(data)
        assert result.get("name") == "钓鱼"

    def test_find_task_section_empty(self):
        """无匹配节点时应返回空字典。"""
        from GameBot.web.api.services import _find_task_section

        assert _find_task_section({}) == {}
        assert _find_task_section({"war3": {}}) == {}

    def test_find_task_section_no_name(self):
        """节点无 name 键时应返回空字典。"""
        from GameBot.web.api.services import _find_task_section

        data = {"war3": {"jiubing2": {"tasks": {"others": {"fishing": {"max_times": 100}}}}}}
        result = _find_task_section(data)
        assert result == {}

    def test_hero_id_regex_valid(self):
        """合法英雄 ID 应匹配正则。"""
        from GameBot.web.api.services import _HERO_ID_RE

        assert _HERO_ID_RE.match("paladin")
        assert _HERO_ID_RE.match("hero_123")
        assert _HERO_ID_RE.match("hero-abc")

    def test_hero_id_regex_invalid(self):
        """非法英雄 ID 不应匹配正则。"""
        from GameBot.web.api.services import _HERO_ID_RE

        assert not _HERO_ID_RE.match("../../etc")
        assert not _HERO_ID_RE.match("hero with space")
        assert not _HERO_ID_RE.match("")

    def test_prune_running_processes(self):
        """_prune_running_processes 应清理已结束的进程。"""
        from GameBot.web.api import services
        from GameBot.web.api.services import _prune_running_processes

        finished_proc = MagicMock()
        finished_proc.poll.return_value = 0
        running_proc = MagicMock()
        running_proc.poll.return_value = None

        services._running_processes.clear()
        services._running_processes["task_a"] = finished_proc
        services._running_processes["task_b"] = running_proc

        _prune_running_processes()

        assert "task_a" not in services._running_processes
        assert "task_b" in services._running_processes
