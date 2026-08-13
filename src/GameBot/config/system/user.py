"""用户配置覆盖 — 加载 user_configs.json / user_config.json、应用用户覆盖到配置字典。"""
import copy
import json


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
        # 兼容旧格式：user_config.json（单个配置对象，无多配置切换）
        old_path = self.project_root / "user_config.json"
        if old_path.exists() and not path.exists():
            try:
                with open(old_path, "r", encoding="utf-8") as f:
                    user_cfg = json.load(f)
            except Exception:
                pass
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 兼容旧多配置格式
                if isinstance(data, dict) and "active" in data and "configs" in data:
                    active = data.get("active", "default")
                    data = data.get("configs", {})
                    user_cfg = data.get(active, {}) if isinstance(data, dict) else {}
                else:
                    user_cfg = data if isinstance(data, dict) else {}
            except Exception:
                pass

        if not task_name:
            return copy.deepcopy(user_cfg) if isinstance(user_cfg, dict) else {}

        short_name = task_name.split(".")[-1] if task_name else None
        full_name = None
        if task_name:
            for prefix in ("war3.jiubing2.tasks.", "tasks."):
                if task_name.startswith(prefix):
                    full_name = task_name[len(prefix):]
                    break

        if isinstance(user_cfg, dict):
            if full_name and full_name in user_cfg and isinstance(user_cfg[full_name], dict):
                return copy.deepcopy(user_cfg[full_name])
            if short_name and short_name in user_cfg and isinstance(user_cfg[short_name], dict):
                return copy.deepcopy(user_cfg[short_name])
            # 兼容旧版平铺：根级别存在通用覆盖字段时直接返回
            if any(k in user_cfg for k in ("hero", "inventory", "desired_items", "patrol_rounds", "points", "chest",
                                           "combat_mode", "route_scheme")):
                return copy.deepcopy(user_cfg)

        return {}

    def _apply_user_overrides(self, config: dict, user_cfg: dict, task_name: str = None):
        """将 user_configs.json 中的用户覆盖应用到配置字典（原地修改）。

        映射关系：
        - hero → 已在 load_task 中处理英雄替换，此处跳过
        - hero_configs → 施法模式下按英雄隔离的 points/inventory，优先应用
        - inventory → config["hero"]["inventory"]（无 hero_configs 时回退）
        - desired_items / patrol_rounds / points → 任务自身命名空间
        - chest → 顶层 [chest]（可继承节点）
        - 其他字段 → 任务自身命名空间（深度合并）
        """
        # 计算任务在 war3.jiubing2.tasks 下的命名空间路径
        # 例：war3.jiubing2.tasks.others.patrol_loot -> ["others", "patrol_loot"]
        task_path = []
        if task_name:
            # 去掉 war3.jiubing2.tasks. 前缀（兼容旧 tasks. 前缀）
            name = task_name
            for prefix in ("war3.jiubing2.tasks.", "tasks."):
                if name.startswith(prefix):
                    name = name[len(prefix):]
                    break
            task_path = [p for p in name.split(".") if p]

        def ensure_task_cfg():
            """确保 config["war3"]["jiubing2"]["tasks"][...task_path] 路径存在并返回最内层 dict。"""
            cfg = config.setdefault("war3", {}).setdefault("jiubing2", {}).setdefault("tasks", {})
            for part in task_path:
                cfg = cfg.setdefault(part, {})
            return cfg

        # hero_configs → 施法模式下按英雄隔离的 points/inventory
        hero_cfgs = user_cfg.get("hero_configs")
        current_hero = user_cfg.get("hero")
        has_hero_config = (
            hero_cfgs and current_hero and current_hero in hero_cfgs
        )

        if has_hero_config:
            hc = hero_cfgs[current_hero]
            # points 可能是数组（普通任务）或对象（每日声望的多路线点）
            if "points" in hc:
                hc_points = hc["points"]
                if isinstance(hc_points, dict):
                    # 每日声望：{blackstone_points: [...], forest_points: [...]}
                    if "blackstone_points" in hc_points:
                        cfg = config.setdefault("war3", {}).setdefault("jiubing2", {}).setdefault("tasks", {}).setdefault("atomic", {}).setdefault("blackstone_gate_harassment", {})
                        cfg["points"] = copy.deepcopy(hc_points["blackstone_points"])
                    if "forest_points" in hc_points:
                        cfg = config.setdefault("war3", {}).setdefault("jiubing2", {}).setdefault("tasks", {}).setdefault("atomic", {}).setdefault("swift_beast", {})
                        cfg["points"] = copy.deepcopy(hc_points["forest_points"])
                else:
                    ensure_task_cfg()["points"] = copy.deepcopy(hc_points)
            if "inventory" in hc:
                config.setdefault("hero", {})["inventory"] = copy.deepcopy(hc["inventory"])
        elif (
            user_cfg.get("combat_mode") == "cast_skills"
            and hero_cfgs
            and current_hero
            and current_hero not in hero_cfgs
        ):
            # 已存在其他英雄的 hero_configs 但当前英雄没有配置：
            # 说明用户手动切换了英雄但未保存，不能回退到顶层的旧英雄数据。
            # 保持配置构建产生的默认值（路线方案预设点 + 英雄默认物品栏）。
            pass
        else:
            # 向后兼容：无 hero_configs 时回退到顶层 inventory / points
            if "inventory" in user_cfg:
                config.setdefault("hero", {})["inventory"] = copy.deepcopy(user_cfg["inventory"])

            if "points" in user_cfg:
                ensure_task_cfg()["points"] = copy.deepcopy(user_cfg["points"])

        # desired_items → 写入任务命名空间
        if "desired_items" in user_cfg:
            ensure_task_cfg()["desired_items"] = copy.deepcopy(user_cfg["desired_items"])

        # patrol_rounds → 写入任务命名空间下的 patrol.rounds
        if "patrol_rounds" in user_cfg:
            task_cfg = ensure_task_cfg()
            patrol_cfg = task_cfg.setdefault("patrol", {})
            patrol_cfg["rounds"] = user_cfg["patrol_rounds"]

        # chest → 深度合并到顶层 [chest]（可继承节点）
        if "chest" in user_cfg:
            chest_cfg = config.setdefault("chest", {})
            self._deep_merge(chest_cfg, user_cfg["chest"])

        # combat_mode → 写入任务命名空间
        if "combat_mode" in user_cfg:
            ensure_task_cfg()["combat_mode"] = user_cfg["combat_mode"]
            # daily_reputation 的子任务各自读自己的 cfg，需同步写入
            daily_cfg = config.setdefault("war3", {}).setdefault("jiubing2", {}).setdefault("tasks", {}).setdefault("reputation", {}).setdefault("daily_reputation", {})
            for _sub in ("blackstone", "forest"):
                if _sub in daily_cfg:
                    daily_cfg[_sub]["combat_mode"] = user_cfg["combat_mode"]

        # route_scheme → 写入任务命名空间
        if "route_scheme" in user_cfg:
            ensure_task_cfg()["route_scheme"] = user_cfg["route_scheme"]

        # blackstone_points → 写入 war3.jiubing2.tasks.atomic.blackstone_gate_harassment.points
        if "blackstone_points" in user_cfg:
            cfg = config.setdefault("war3", {}).setdefault("jiubing2", {}).setdefault("tasks", {}).setdefault("atomic", {}).setdefault("blackstone_gate_harassment", {})
            cfg["points"] = copy.deepcopy(user_cfg["blackstone_points"])

        # forest_points → 写入 war3.jiubing2.tasks.atomic.swift_beast.points
        if "forest_points" in user_cfg:
            cfg = config.setdefault("war3", {}).setdefault("jiubing2", {}).setdefault("tasks", {}).setdefault("atomic", {}).setdefault("swift_beast", {})
            cfg["points"] = copy.deepcopy(user_cfg["forest_points"])

        # 其余字段 → 合并到任务命名空间（跳过已处理的特殊键）
        if task_path:
            task_cfg = ensure_task_cfg()
            for key, value in user_cfg.items():
                if key in {"hero", "hero_configs", "inventory", "desired_items", "patrol_rounds",
                           "chest", "points", "combat_mode", "route_scheme",
                           "blackstone_points", "forest_points"}:
                    continue
                task_cfg[key] = copy.deepcopy(value) if isinstance(value, (dict, list)) else value
