"""配置系统核心 — Config 单例类，组合所有 mixin，提供配置加载和访问接口。

继承规则：
1. 依赖继承：配置文件通过 name 声明自身命名空间、extends = ["tasks.xxx", "heroes.yyy"] 声明继承，
   按深度优先后序展开为线性加载顺序（每个文件只加载一次，类似 Python import），
   同名可继承节点深度合并（未覆盖的字段从父配置继承，已覆盖的字段递归覆盖）。
   文件内使用 [this] 简写代替完整命名空间前缀。
2. 命名空间约定：config 目录下的一级文件夹名和顶层 .toml 文件名构成命名空间根
   （如 war3、team、base、kk、web）。TOML 顶层键命中命名空间根的（如 [war3]）
   保留在路径下；hero 是唯一保留在顶层的键（局内唯一英雄，任务层横向覆盖英雄层）。
   其余裸键不再提升到顶层（旧"共享区"已废弃）——请用 [this.xxx] 归入自身命名空间。
   不递归扫描子目录——新建子目录不会改变现有 TOML 的合并语义。
3. 英雄互斥：一场游戏只能玩一个英雄。heroes.* 配置互斥生效——加载顺序中最后一个
   英雄配置整体替换之前英雄贡献的顶层节点。
4. [hero] 浅合并：[hero] 是顶层键但做浅合并处理——合并顶层子键（skills/
   inventory/stigma/cards 等），每个子键完全覆盖（不递归）。任务配置只写
   inventory 不会丢失英雄的 skills 等属性。
5. 结果结构：类 JSON 字典。hero 在顶层，其余配置保留在各自命名空间路径下
   （如 result["war3"]["jiubing2"]["tasks"]["atomic"]["xxx"]）。
   result["_extends"] 记录各配置文件的 extends 依赖映射，供 get_task_view 沿链
   合并任务视图（变体不写的参数自动从基任务继承）。
- 不硬编码任何配置文件名，用户配置了哪些依赖就导入哪些

模块结构：
- base.py     — ConfigurationError 异常 + 常量
- loader.py   — 文件加载 & 命名空间拆分
- resolver.py — 依赖解析（DFS 后序展开）
- builder.py  — 合并构建 & 深度合并
- user.py     — 用户配置覆盖
- core.py     — Config 类 + 单例 + load_task + 访问方法（本文件）
"""

import copy
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import CONTROL_KEYS, EXCLUSIVE_NAMESPACES
from .builder import ConfigBuilderMixin
from .derive import derive_bind_mode, get_task_view, resolve_item_names, select_bind_cfg
from .loader import ConfigLoaderMixin
from .resolver import ConfigResolverMixin
from .user import ConfigUserMixin


class Config(ConfigLoaderMixin, ConfigResolverMixin, ConfigBuilderMixin, ConfigUserMixin):
    """全局配置单例 — 通过多继承组合各 mixin 的能力。

    职责划分（mixin 模块）：
    - ConfigLoaderMixin   — TOML 文件加载缓存、命名空间拆分
    - ConfigResolverMixin — DFS 后序依赖解析、循环依赖检测
    - ConfigBuilderMixin  — 合并构建、深度合并、英雄互斥
    - ConfigUserMixin     — user_configs.json 加载与覆盖应用

    本类自身保留：单例控制、load_task 编排、配置访问方法（get/get_section/[]）。
    """

    _EXCLUSIVE_NAMESPACES = EXCLUSIVE_NAMESPACES
    _CONTROL_KEYS = CONTROL_KEYS

    _instance: Optional["Config"] = None
    _instance_lock = threading.Lock()  # 单例创建锁，保证多线程下只创建一个实例
    _config: dict  # 全局合并后的配置字典
    _loaded_files: Dict[str, dict]  # 配置名 -> 原始 TOML 解析结果（缓存）
    _task_configs: Dict[str, Tuple[dict, float, Dict[str, List[str]]]]  # 任务名 -> (合并后配置, user_configs.json 的 mtime, provenance)
    _load_order: List[str]  # 全局加载顺序（跨多次 load_task 累积）
    _initialized: bool

    def __new__(cls, config_path: Optional[str] = None):
        # 双重检查锁：第一次检查避免已创建后每次加锁的开销，
        # 锁内第二次检查防止两个线程同时通过第一次检查后重复创建。
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._config = {}
                    cls._instance._loaded_files = {}
                    cls._instance._task_configs = {}
                    cls._instance._load_order = []
                    cls._instance._provenance = {}
                    cls._instance._ns_roots = None
                    cls._instance._initialized = False
                    cls._instance._resource_manager = None
                    cls._instance._project_root_override = None
                    if config_path is not None:
                        cls._instance.config_path = Path(config_path)
                    else:
                        # 默认指向 src/GameBot/config/data/
                        cls._instance.config_path = Path(__file__).parent.parent / "data"
        return cls._instance

    @property
    def config_dir(self) -> Path:
        """配置目录路径（即 config_path 本身）。"""
        return self.config_path

    @property
    def project_root(self) -> Path:
        """项目根目录 = config_path 上溯四级（data/ → config/ → GameBot/ → src/ → 项目根）。

        若设置了 _project_root_override（exe 打包环境），直接返回该值。
        """
        if self._project_root_override is not None:
            return self._project_root_override
        return self.config_path.parent.parent.parent.parent

    def get_path(self, key: str, default: str = "") -> Path:
        """获取配置中的路径值并返回绝对路径。

        配置中的相对路径以 project_root 为基准解析为绝对路径。
        """
        value = self.get(key, default)
        if not value:
            return self.project_root
        path = Path(value)
        if not path.is_absolute():
            path = self.project_root / path
        return path

    def load_task(self, task_name: str) -> dict:
        """按需加载任务配置及其依赖，结果缓存，并同步到全局 _config。

        返回值为该任务自身依赖闭包的合并结果；全局 _config 按全局加载顺序
        重建，跨多次 load_task 仍保持"后加载英雄互斥、后加载覆盖"语义。

        若项目根目录存在 user_config.json，会先加载并应用用户覆盖：
        - hero 字段替换英雄依赖（如 "lancer" → heroes.lancer）
        - inventory / desired_items / patrol_rounds / chest 等字段深度合并到结果
        """
        # 命中缓存直接返回，避免重复解析依赖链
        # 但需检查 user_configs.json 是否被修改（mtime 变化则缓存失效）
        user_cfg_path = self.project_root / "user_configs.json"
        old_user_path = self.project_root / "user_config.json"
        current_mtime = 0.0
        for p in (user_cfg_path, old_user_path):
            if p.exists():
                current_mtime = max(current_mtime, os.path.getmtime(p))
        if task_name in self._task_configs:
            cached_result, cached_mtime, _cached_prov = self._task_configs[task_name]
            if cached_mtime == current_mtime:
                return cached_result
            # user_configs.json 已修改，清除该任务的缓存
            del self._task_configs[task_name]

        # 第一步：DFS 解析依赖，得到线性加载顺序
        order: List[str] = []
        self._resolve_order(task_name, order, [], set())

        # 第二步：应用 user_configs.json 中的英雄替换
        # 用户指定的英雄覆盖任务配置中声明的 heroes.* 依赖
        user_cfg = self._load_user_config(task_name)
        if user_cfg and "hero" in user_cfg:
            hero_name = user_cfg["hero"]
            hero_config_name = f"war3.jiubing2.heroes.{hero_name}"
            hero_path = self._file_path_for(hero_config_name)
            if hero_path.exists():
                # 将加载顺序中所有 war3.jiubing2.heroes.* 替换为用户指定的英雄
                order = [hero_config_name if name.startswith("war3.jiubing2.heroes.") else name for name in order]
                # 预加载用户英雄配置到缓存
                if hero_config_name not in self._loaded_files:
                    self._load_file(hero_config_name)

        # 第三步：按加载顺序合并配置（同时记录 provenance：dot_path -> 来源链）
        prov: Dict[str, List[str]] = {}
        result = self._build(order, prov)

        # 第四步：应用 user_configs.json 中的其他覆盖（inventory/desired_items 等）
        if user_cfg:
            self._apply_user_overrides(result, user_cfg, task_name, prov=prov)

        # 将 kk.inventory_slots 注入 hero_cfg，供 get_inventory_hotkey(s) 查找快捷键
        self._inject_inventory_slots(result, prov)
        # 将 inventory 中的 item 物品名解析为 item_id
        self._resolve_inventory_item_names(result, prov)
        # 根据 bind_mode 切换前台/后台绑定配置（任务级 this.bind_mode 可覆盖）
        self._apply_bind_mode(result, task_name, prov)

        # 缓存任务结果（含 user_configs.json 的 mtime 与 provenance，用于缓存失效检测与 explain）
        self._task_configs[task_name] = (result, current_mtime, prov)

        # 第五步：同步全局 _config
        # 将本次加载的文件追加到全局加载顺序（去重），重建全局配置
        for name in order:
            if name not in self._load_order:
                self._load_order.append(name)
        global_prov: Dict[str, List[str]] = {}
        rebuilt = self._build(self._load_order, global_prov)
        if user_cfg:
            self._apply_user_overrides(rebuilt, user_cfg, task_name, prov=global_prov)
        self._inject_inventory_slots(rebuilt, global_prov)
        self._resolve_inventory_item_names(rebuilt, global_prov)
        self._apply_bind_mode(rebuilt, task_name, global_prov)
        self._config.clear()
        self._config.update(rebuilt)
        self._provenance = global_prov
        return result

    def _inject_inventory_slots(self, config: dict, prov=None):
        """将 kk.inventory_slots 注入 hero.inventory_slots，供快捷键查找使用。

        kk.toml 中定义了默认的格子→快捷键映射，hero_cfg 通过 inventory_slots
        字段访问该映射。组队配置中成员可用 inventory_slots 覆盖默认值。
        """
        kk_cfg = config.get("kk", {})
        if not isinstance(kk_cfg, dict):
            return
        kk_slots = kk_cfg.get("inventory_slots")
        if kk_slots:
            hero = config.setdefault("hero", {})
            if "inventory_slots" not in hero:
                hero["inventory_slots"] = copy.deepcopy(kk_slots)
                self._prov_mark(prov, "hero.inventory_slots", "<派生:kk.inventory_slots>")

    def _resolve_inventory_item_names(self, config: dict, prov=None):
        """将 hero.inventory 中的 item（物品名）解析为 item_id（原地修改）。

        支持用物品名替代数字 ID，提升配置可读性。已有 item_id 的条目不受影响。
        物品名→ID 映射来自配置中的 items 列表（war3.jiubing2.items）。
        实际解析逻辑在 derive.resolve_item_names（组队路径复用）。
        """
        hero = config.get("hero", {})
        j2_cfg = config.get("war3", {}).get("jiubing2", {})
        if not isinstance(j2_cfg, dict):
            return
        if resolve_item_names(hero.get("inventory", []), j2_cfg.get("items", [])):
            self._prov_mark(prov, "hero.inventory", "<派生:物品名→item_id>")

    def _apply_bind_mode(self, config: dict, task_name: str = None, prov=None):
        """按 bind_mode 解析前台/后台绑定参数，结果写入 config[ns]["bind"]。

        优先级：任务段 bind_mode > target_player 推导 > 平台级 bind_mode。
        实际推导/写入逻辑在 derive 模块（derive_bind_mode / select_bind_cfg），
        组队多成员强转后台由 team/base.py 调 derive.apply_bind_mode 完成。
        """
        # 任务级覆盖：沿 extends 链合并任务视图（含变体继承）；
        # 非任务入口（kk/team.* 等）get_task_view 返回空字典
        task_node = get_task_view(config, task_name) if task_name else None

        for ns in ("war3", "kk"):
            ns_cfg = config.get(ns)
            if not isinstance(ns_cfg, dict):
                continue
            mode = derive_bind_mode(task_node, ns_cfg)
            src_key = select_bind_cfg(ns_cfg, mode)
            if src_key:
                self._prov_mark(prov, f"{ns}.bind", f"<派生:{src_key}>")

    def get_section(self, section: str, task_name: str = None) -> dict:
        """获取配置段（已含任务级覆盖），返回字典。

        load_task 时已将依赖链中的同名段深度合并到全局 _config，
        此方法直接从全局配置中取已合并的结果。

        :param section: 配置段名（如 "chest", "pickup"）
        :param task_name: 任务名（保留扩展用，当前从全局合并结果获取）
        :return: 配置段字典，不存在则返回空字典
        """
        result = self.get(section, {})
        return result if isinstance(result, dict) else {}

    def get(self, dot_path: str, default: Any = None) -> Any:
        """按 dot 路径读取配置值，不存在则返回 default。

        例：get("hero.inventory") → self._config["hero"]["inventory"]
        """
        keys = dot_path.split(".")
        value = self._config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def __getitem__(self, key: str) -> Any:
        """直接下标访问顶层配置段，如 config["hero"]。"""
        return self._config[key]

    def __contains__(self, key: str) -> bool:
        """判断顶层是否包含某配置段，如 "hero" in config。"""
        return key in self._config

    @property
    def resource_manager(self):
        """延迟初始化 ResourceManager（避免循环导入）。"""
        if self._resource_manager is None:
            from GameBot.runner.resource_manager import ResourceManager

            self._resource_manager = ResourceManager()
        return self._resource_manager

    @property
    def config(self) -> dict:
        """全局合并后的配置字典（只读视图）。"""
        return self._config

    def get_provenance(self, task_name: str = None) -> Dict[str, List[str]]:
        """返回 provenance 映射：dot_path -> [写入来源链]（按写入顺序，末位为生效来源）。

        来源为配置名（如 "war3.jiubing2.tasks.endless.endless_善木木"）、
        "user_configs.json" 或 "<派生:xxx>"（bind/inventory_slots/物品名解析等派生步骤）。

        :param task_name: 指定任务返回其依赖闭包的 provenance（须先 load_task）；
            None 返回全局 _config 的 provenance
        """
        if task_name is None:
            return self._provenance
        entry = self._task_configs.get(task_name)
        return entry[2] if entry else {}

    @staticmethod
    def reset():
        """重置单例 — 仅用于测试，生产代码不应调用。"""
        Config._instance = None


def get_config() -> Config:
    """返回全局配置实例"""
    return config


config = Config()
