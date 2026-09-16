"""用户配置覆盖 — 加载 user_configs.json / user_config.json、应用用户覆盖到配置字典。"""

import copy


class ConfigUserMixin:
    """Config 的用户配置覆盖 mixin。

    依赖 self.project_root（Path）、self._deep_merge()（ConfigBuilderMixin 提供）。
    """

    def _load_user_config(self, task_name: str = None) -> dict:
        """加载项目根目录的 user_configs.json，返回当前任务的用户覆盖。

        文件格式：{ "<task_id>": {...} }，兼容旧格式 { active: "...", configs: {...} }。
        支持两种任务名匹配：全名（去掉 "tasks." 前缀）和短名（最后一段）。
        """
        path = self.project_root / "user_configs.json"
        user_cfg = {}
        # 延迟导入，避免 config → utils → logger → config 循环依赖
        from GameBot.utils.file_io import load_json

        # 兼容旧格式：user_config.json（单个配置对象，无多配置切换）
        old_path = self.project_root / "user_config.json"
        if old_path.exists() and not path.exists():
            data = load_json(old_path)
            user_cfg = data if isinstance(data, dict) else {}
        elif path.exists():
            data = load_json(path)
            if isinstance(data, dict):
                # 兼容旧多配置格式
                if "active" in data and "configs" in data:
                    active = data.get("active", "default")
                    data = data.get("configs", {})
                    user_cfg = data.get(active, {}) if isinstance(data, dict) else {}
                else:
                    user_cfg = data

        if not task_name:
            return copy.deepcopy(user_cfg) if isinstance(user_cfg, dict) else {}

        short_name = task_name.split(".")[-1] if task_name else None
        full_name = None
        if task_name:
            for prefix in ("war3.jiubing2.tasks.", "tasks."):
                if task_name.startswith(prefix):
                    full_name = task_name[len(prefix) :]
                    break

        if isinstance(user_cfg, dict):
            if full_name and full_name in user_cfg and isinstance(user_cfg[full_name], dict):
                return copy.deepcopy(user_cfg[full_name])
            if short_name and short_name in user_cfg and isinstance(user_cfg[short_name], dict):
                return copy.deepcopy(user_cfg[short_name])
            # 兼容旧版平铺：根级别存在通用覆盖字段时直接返回
            if any(
                k in user_cfg
                for k in (
                    "hero",
                    "inventory",
                    "desired_items",
                    "patrol_rounds",
                    "points",
                    "chest",
                    "combat_mode",
                    "route_scheme",
                )
            ):
                return copy.deepcopy(user_cfg)

        return {}

    # user_configs.json 写入时记录到 provenance 的来源名
    _USER_SRC = "user_configs.json"

    # 用户覆盖键 → [(目标路径, 是否自动创建中间节点)]
    # "{task}" 占位当前任务命名空间（war3.jiubing2.tasks.<路径>）；
    # create=False 表示目标父路径不存在则跳过（条件性同步子节点，不凭空造节点）。
    _USER_KEY_ROUTES = {
        "inventory": [("hero.inventory", True)],
        "points": [("{task}.points", True)],
        "desired_items": [("{task}.desired_items", True)],
        "patrol_rounds": [("{task}.patrol.rounds", True)],
        "route_scheme": [("{task}.route_scheme", True)],
        "combat_mode": [
            ("{task}.combat_mode", True),
            # daily_reputation 的子任务各自读自己的 cfg，需同步写入（仅在闭包内存在时）
            ("war3.jiubing2.tasks.reputation.daily_reputation.blackstone.combat_mode", False),
            ("war3.jiubing2.tasks.reputation.daily_reputation.forest.combat_mode", False),
        ],
        "blackstone_points": [("war3.jiubing2.tasks.atomic.blackstone_gate_harassment.points", True)],
        "forest_points": [("war3.jiubing2.tasks.atomic.swift_beast.points", True)],
    }

    # 特殊键：不走通用路由
    # - hero: 由 load_task 做英雄替换（互斥组重排序）
    # - hero_configs: 施法模式下按英雄隔离的 points/inventory
    # - chest: 深度合并到顶层 [chest]（可继承节点）
    _USER_SPECIAL_KEYS = frozenset({"hero", "hero_configs", "chest"})

    def _apply_user_overrides(self, config: dict, user_cfg: dict, task_name: str = None, prov=None):
        """将 user_configs.json 中的用户覆盖应用到配置字典（原地修改）。

        路由由 _USER_KEY_ROUTES 声明式表驱动：键 → [(目标路径, 是否创建中间节点)]，
        "{task}" 展开为当前任务命名空间；未列出的键兜底写入任务命名空间。
        特殊键单独处理（见 _USER_SPECIAL_KEYS）。

        :param prov: 可选 provenance 输出字典，记录各写入路径的来源为 user_configs.json
        """
        # 计算任务在 war3.jiubing2.tasks 下的命名空间路径
        # 例：war3.jiubing2.tasks.others.patrol_loot -> ["others", "patrol_loot"]
        task_path = []
        if task_name:
            # 去掉 war3.jiubing2.tasks. 前缀（兼容旧 tasks. 前缀）
            name = task_name
            for prefix in ("war3.jiubing2.tasks.", "tasks."):
                if name.startswith(prefix):
                    name = name[len(prefix) :]
                    break
            task_path = [p for p in name.split(".") if p]
        task_ns = "war3.jiubing2.tasks" + ("." + ".".join(task_path) if task_path else "")

        def user_set(dot_path: str, value, source: str, create: bool = True):
            """按 dot 路径写入用户覆盖值；create=False 时中间路径不存在则跳过。"""
            node = config
            parts = dot_path.split(".")
            for p in parts[:-1]:
                node = node.setdefault(p, {}) if create else node.get(p)
                if not isinstance(node, dict):
                    return
            node[parts[-1]] = copy.deepcopy(value) if isinstance(value, (dict, list)) else value
            self._prov_mark(prov, dot_path, source)

        # hero_configs → 施法模式下按英雄隔离的 points/inventory（优先于顶层 inventory/points）
        hero_cfgs = user_cfg.get("hero_configs")
        current_hero = user_cfg.get("hero")
        has_hero_config = bool(hero_cfgs and current_hero and current_hero in hero_cfgs)
        # 已存在其他英雄配置但当前英雄没有：用户手动切了英雄未保存，
        # 不回退顶层旧英雄数据，保持配置构建的默认值（路线方案预设点 + 英雄默认物品栏）
        stale_hero = (
            user_cfg.get("combat_mode") == "cast_skills"
            and isinstance(hero_cfgs, dict)
            and bool(current_hero)
            and current_hero not in hero_cfgs
        )
        if has_hero_config:
            hc_source = f"{self._USER_SRC}:hero_configs.{current_hero}"
            hc = hero_cfgs[current_hero]
            hc_points = hc.get("points")
            if isinstance(hc_points, dict):
                # 每日声望多路线：{blackstone_points: [...], forest_points: [...]} 复用路由表
                for key, value in hc_points.items():
                    for tpl, create in self._USER_KEY_ROUTES.get(key, ()):
                        user_set(tpl.format(task=task_ns), value, hc_source, create)
            elif hc_points is not None:
                user_set(f"{task_ns}.points", hc_points, hc_source)
            if "inventory" in hc:
                user_set("hero.inventory", hc["inventory"], hc_source)

        # chest → 深度合并到顶层 [chest]（可继承节点）
        if "chest" in user_cfg:
            self._deep_merge(
                config.setdefault("chest", {}),
                user_cfg["chest"],
                _path="chest",
                _prov=prov,
                _source=self._USER_SRC,
            )

        # 通用路由：表中键按声明路径写入；未列出键兜底到任务命名空间（需有任务路径）
        for key, value in user_cfg.items():
            if key in self._USER_SPECIAL_KEYS:
                continue
            if key in ("inventory", "points") and (has_hero_config or stale_hero):
                continue
            routes = self._USER_KEY_ROUTES.get(key)
            if routes is None:
                if not task_path:
                    continue
                routes = [(f"{{task}}.{key}", True)]
            for tpl, create in routes:
                user_set(tpl.format(task=task_ns), value, self._USER_SRC, create)
