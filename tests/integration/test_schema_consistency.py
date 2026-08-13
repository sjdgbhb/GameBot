"""TASK_SCHEMAS 与任务脚本/配置一一对应验证。

验证：
- TASK_SCHEMAS 中每个 task_id 对应的 TOML 配置文件存在
- TASK_SCHEMAS 中每个 task_id 对应的 runner 脚本文件存在（is_runnable_task）
- 真实配置目录中的可配置任务都在 TASK_SCHEMAS 中有对应 schema
"""
import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

pytestmark = [pytest.mark.integration]

from GameBot.web.api.services import TASK_SCHEMAS, is_runnable_task, load_tasks

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_DIR = _PROJECT_ROOT / "src" / "GameBot" / "config" / "data"
_TASKS_DIR = _CONFIG_DIR / "war3" / "jiubing2" / "tasks"


def _resolve_task_toml(task_id: str) -> Path | None:
    """将 task_id 解析为 TOML 文件路径，支持短 ID 和全 ID。

    短 ID（如 patrol_loot）会在 tasks/ 子目录中搜索匹配文件。
    全 ID（如 others.fishing）直接拼接路径。
    """
    # 全 ID 直接拼接
    toml_path = _TASKS_DIR / Path(*task_id.split(".")).with_suffix(".toml")
    if toml_path.exists():
        return toml_path
    # 短 ID 在子目录中搜索
    if "." not in task_id:
        for p in _TASKS_DIR.rglob(f"{task_id}.toml"):
            return p
    return None


def _resolve_full_task_id(task_id: str) -> str | None:
    """将短 ID 解析为全 ID（如 patrol_loot → others.patrol_loot）。"""
    if "." in task_id:
        return task_id
    for p in _TASKS_DIR.rglob(f"{task_id}.toml"):
        rel = p.relative_to(_TASKS_DIR).with_suffix("")
        return ".".join(rel.parts)
    return None


class TestTaskSchemaConsistency:
    """TASK_SCHEMAS 与实际文件一一对应。"""

    def test_schema_task_ids_have_toml_files(self):
        """TASK_SCHEMAS 中每个 task_id 应有对应 TOML 配置文件。"""
        missing = []
        for task_id in TASK_SCHEMAS:
            toml_path = _resolve_task_toml(task_id)
            if toml_path is None or not toml_path.exists():
                missing.append(task_id)
        assert not missing, f"TASK_SCHEMAS 中以下 task_id 无对应 TOML: {missing}"

    def test_schema_task_ids_are_runnable(self):
        """TASK_SCHEMAS 中每个 task_id 应可通过 is_runnable_task 检查。

        短 ID（如 patrol_loot）需先解析为全 ID（others.patrol_loot）再检查。
        """
        not_runnable = []
        for task_id in TASK_SCHEMAS:
            full_id = _resolve_full_task_id(task_id) or task_id
            if not is_runnable_task(full_id):
                not_runnable.append(task_id)
        assert not not_runnable, (
            f"TASK_SCHEMAS 中以下 task_id 不可执行: {not_runnable}"
        )

    def test_schema_has_required_top_level_fields(self):
        """每个 schema 应含 id, name, description, sections 字段。"""
        required = {"id", "name", "description", "sections"}
        for task_id, schema in TASK_SCHEMAS.items():
            missing = required - set(schema.keys())
            assert not missing, f"schema '{task_id}' 缺少字段: {missing}"

    def test_schema_sections_have_key_and_title(self):
        """每个 section 应含 key 和 title 字段。"""
        for task_id, schema in TASK_SCHEMAS.items():
            for section in schema.get("sections", []):
                assert "key" in section, f"schema '{task_id}' section 缺少 key"
                assert "title" in section, f"schema '{task_id}' section 缺少 title"

    def test_schema_ids_match_dict_keys(self):
        """schema 内部 id 应与 TASK_SCHEMAS 的 key 一致。"""
        for task_id, schema in TASK_SCHEMAS.items():
            assert schema.get("id") == task_id, (
                f"schema key='{task_id}' 但内部 id='{schema.get('id')}'"
            )

    def test_configurable_tasks_have_schemas(self):
        """load_tasks() 中标记为 configurable=True 的任务应在 TASK_SCHEMAS 中有 schema。"""
        tasks = load_tasks()
        configurable_ids = {t["id"] for t in tasks if t.get("configurable")}
        schema_ids = set(TASK_SCHEMAS.keys())
        # 也检查短 id 匹配
        schema_short_ids = {sid.split(".")[-1] for sid in TASK_SCHEMAS.keys()}
        missing = []
        for tid in configurable_ids:
            if tid not in schema_ids and tid.split(".")[-1] not in schema_short_ids:
                missing.append(tid)
        assert not missing, (
            f"以下 configurable 任务缺少 TASK_SCHEMAS: {missing}"
        )
