"""配置文件加载 & 命名空间拆分。

包含 Config 的文件 I/O mixin：配置名到文件路径映射、TOML 加载缓存、
命名空间根集合发现、可继承/命名空间节点拆分。
"""

import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib
from pathlib import Path
from typing import FrozenSet, Tuple

from .base import ConfigurationError


class ConfigLoaderMixin:
    """Config 的文件加载 mixin。

    依赖 self.config_dir（Path）、self._loaded_files（dict）、self._ns_roots。
    """

    def _file_path_for(self, config_name: str) -> Path:
        """配置名到文件路径映射：dot 路径直接映射到 config 目录下的文件。

        支持三种文件布局（按优先级尝试）：
        1. config_dir / a / b / c.toml       — 标准路径（最常见）
        2. config_dir / a / b / c / c.toml   — 目录内同名文件（如 war3/war3.toml）
        3. config_dir / a / b / c / base.toml — 目录内 base.toml（如根 base.toml）

        例：war3.jiubing2.heroes.hxd -> config/war3/jiubing2/heroes/hxd.toml
            war3 -> config/war3/war3.toml
            war3.jiubing2 -> config/war3/jiubing2/jiubing2.toml
        """
        parts = config_name.split(".")
        # 标准路径: config_dir / a / b / c.toml
        path = self.config_dir / Path(*parts[:-1]) / f"{parts[-1]}.toml"
        if path.exists():
            return path
        # 回退1: config_dir / a / b / c / c.toml（目录内同名文件）
        alt_path = self.config_dir / Path(*parts) / f"{parts[-1]}.toml"
        if alt_path.exists():
            return alt_path
        # 回退2: config_dir / a / b / c / base.toml（目录内 base.toml）
        base_path = self.config_dir / Path(*parts) / "base.toml"
        if base_path.exists():
            return base_path
        # 都不存在，返回标准路径（让调用方报错）
        return path

    def _load_file(self, config_name: str) -> dict:
        """加载单个配置文件，命中缓存则直接返回原始缓存。

        缓存以配置名为键，同一文件在依赖链中被多个配置引用时只读取一次。
        支持 name/extends 新格式，并将 [this] 简写展开为完整命名空间路径。
        """
        # 命中缓存直接返回，避免重复磁盘 I/O 和 TOML 解析
        if config_name in self._loaded_files:
            return self._loaded_files[config_name]
        filepath = self._file_path_for(config_name)
        if not filepath.exists():
            raise ConfigurationError(f"配置文件不存在: {config_name} -> {filepath}")
        # tomllib/tomli 要求二进制模式读取
        with open(filepath, "rb") as f:
            data = tomllib.load(f)
        # 拒绝旧格式：顶层直接用 [war3] / [tasks.xxx] 等命名空间根键
        self._reject_old_namespace_sections(data, config_name, filepath)
        # 展开 [this] 简写
        data = self._expand_shorthand(data, config_name)
        self._loaded_files[config_name] = data
        return data

    def _reject_old_namespace_sections(self, raw: dict, config_name: str, filepath: Path):
        """拒绝旧格式 TOML：顶层直接出现命名空间根键（如 [war3]、[tasks.xxx]）。

        所有文件统一用 [this] 表示自己的命名空间。
        """
        roots = self.namespace_roots
        for key in raw:
            if key in self._CONTROL_KEYS:
                continue
            if key == "this":
                continue
            if key in roots:
                raise ConfigurationError(
                    f"{config_name} ({filepath}): 请使用 [this] 简写，"
                    f"不要直接写 [{key}]（旧命名空间格式已废弃）"
                )

    @staticmethod
    def _place_at_path(raw: dict, path: str, value):
        """将 value 按点路径 path 放入 raw 中（就地修改）。

        路径中间层级不存在时自动创建空 dict；若最终键已存在则抛出冲突异常。
        """
        parts = path.split(".")
        d = raw
        for p in parts[:-1]:
            if p not in d or not isinstance(d[p], dict):
                d[p] = {}
            d = d[p]
        last = parts[-1]
        if last in d:
            raise ConfigurationError(f"[this] 简写与已有的 [{path}] 命名空间冲突")
        d[last] = value

    def _expand_shorthand(self, raw: dict, config_name: str) -> dict:
        """将 [this] 简写展开为以 name（或 config_name）为路径的完整命名空间。

        这样任务 TOML 不需要重复写 [war3.jiubing2.tasks.xxx.yyy] 完整路径。
        无 [this] 的文件直接返回（如 jiubing2.toml 等纯可继承配置）。
        """
        if "this" not in raw:
            return raw
        layer_name = raw.get("name", config_name)
        self._place_at_path(raw, layer_name, raw.pop("this"))
        return raw

    @property
    def namespace_roots(self) -> FrozenSet[str]:
        """命名空间根集合：config 目录下的一级文件夹名与顶层 *.toml 文件名（去后缀）。

        只扫描一级目录和顶层 .toml 文件，不递归子目录。
        这样一级目录名（如 war3、team）和顶层文件名（如 base、kk、web）是命名空间根，
        而子目录名（如 tasks、atomic、heroes、scenes）不参与判定——
        新建子目录不会改变现有 TOML 的合并语义。
        TOML 顶层键命中命名空间根 → 不可继承（保留在路径下）；
        未命中 → 可继承（提升到结果顶层）。
        """
        if self._ns_roots is None:
            roots = set()
            if self.config_dir.is_dir():
                for entry in self.config_dir.iterdir():
                    if entry.is_dir():
                        # 一级子目录名是命名空间根（如 war3/、team/）
                        roots.add(entry.name)
                    elif entry.suffix == ".toml":
                        # 顶层 .toml 文件名（去后缀）也是命名空间根（如 base、kk、web）
                        roots.add(entry.stem)
            self._ns_roots = frozenset(roots)
        return self._ns_roots

    def _split_sections(self, raw: dict) -> Tuple[dict, dict]:
        """按命名空间约定拆分文件顶层节点（规则 2）。

        :param raw: 单个配置文件解析后的原始字典
        :return: (可继承节点, 命名空间节点)，控制键（name/extends 等）被剔除
        """
        inheritable, namespaced = {}, {}
        roots = self.namespace_roots
        for key, value in raw.items():
            # 控制键（dependencies/inherit）不参与合并，直接跳过
            if key in self._CONTROL_KEYS:
                continue
            if key in roots:
                # 键名命中命名空间根 → 不可继承，保留在命名空间路径下
                namespaced[key] = value
            else:
                # 键名不在命名空间根 → 可继承，提升到顶层
                inheritable[key] = value
        return inheritable, namespaced
