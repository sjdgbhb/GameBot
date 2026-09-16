"""配置文件加载 & 命名空间拆分。

包含 Config 的文件 I/O mixin：配置名到文件路径映射、TOML 加载缓存、
命名空间根集合发现、可继承/命名空间节点拆分。
"""

import logging
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib
from pathlib import Path
from typing import FrozenSet, Tuple

from .base import NAMESPACE_ROOTS, ConfigurationError


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
        """旧格式拦截：禁止用完整路径段定义文件**自身**命名空间。

        判定：按 config_name 的点路径在 raw 中逐层下钻，能走到自身节点即命中
        （如 config_name=war3.jiubing2.tasks.x.y 的文件写了 [war3.jiubing2.tasks.x.y]
        或更深路径）—— 请改用 [this] / [this.x]。

        **跨层覆盖放行**：一级命名空间根下的**其他**路径不拦截——
        任何文件都可以写 [war3.xxx] / [kk.xxx] / [war3.jiubing2.tasks.others.fishing] 等
        绝对路径，对闭包内其他节点打补丁（含祖先路径，如编排任务调子任务参数）。
        只有"写自身命名空间根"（如 war3.toml 写 [war3]）才拦截，防旧格式回潮。
        """
        parts = config_name.split(".")
        node = raw
        for p in parts:
            if not isinstance(node, dict) or p not in node:
                return  # 未触及自身路径，放行
            node = node[p]
        raise ConfigurationError(
            f"{config_name} ({filepath}): 请使用 [this] 简写定义自身命名空间，"
            f"不要写完整路径 [{config_name}]（如需给其他节点打补丁，写目标的完整路径段即可）"
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
        """将 [this] 简写展开为完整命名空间路径。

        展开路径由加载名（文件路径）推导，无需在 TOML 里声明顶层 name。
        无 [this] 的文件直接返回（如 jiubing2.toml 等纯可继承配置）。
        """
        if "this" not in raw:
            return raw
        self._place_at_path(raw, config_name, raw.pop("this"))
        return raw

    @property
    def namespace_roots(self) -> FrozenSet[str]:
        """命名空间根集合：显式注册表 NAMESPACE_ROOTS（不随目录扫描变化）。

        只登记一级领域名（war3/kk/team/base/web）；war3 内部的 tasks/heroes/scenes
        等子目录不参与判定——新增任务/英雄/场景/变体文件无需登记。
        config_dir 下出现未登记的一级目录或顶层 .toml 时告警：其顶层键会被当作
        命名空间节点保留在路径下（多半不是预期），新增一级命名空间请登记 NAMESPACE_ROOTS。
        TOML 顶层键命中命名空间根 → 保留在路径下（命名空间节点）；
        hero → 顶层键（局内唯一英雄，任务横向覆盖英雄层的通道）；
        其余裸键 → 报错（旧"共享区"已废弃，请用 [this.xxx] 归入命名空间）。
        """
        if self._ns_roots is None:
            if self.config_dir.is_dir():
                for entry in self.config_dir.iterdir():
                    if entry.is_dir():
                        name = entry.name
                    elif entry.suffix == ".toml":
                        name = entry.stem
                    else:
                        continue
                    if name not in NAMESPACE_ROOTS:
                        logging.getLogger(__name__).warning(
                            "配置目录存在未登记的一级条目 %s：不会作为命名空间根"
                            "（其顶层键将提升为可继承共享键）；如需新增一级命名空间，"
                            "请登记到 config/system/base.py 的 NAMESPACE_ROOTS",
                            entry.name,
                        )
            self._ns_roots = NAMESPACE_ROOTS
        return self._ns_roots

    def _split_sections(self, raw: dict) -> Tuple[dict, dict]:
        """按命名空间约定拆分文件顶层节点。

        :param raw: 单个配置文件解析后的原始字典（[this] 已展开为完整路径）
        :return: (顶层键, 命名空间节点)，控制键（name/extends 等）被剔除

        规则：
        - hero → 顶层键（局内唯一英雄，任务层横向覆盖英雄层的通道）
        - 命名空间根键（war3/kk/base/team/web）→ 命名空间节点，保留在路径下
        - 其余裸键 → 报错：请用 [this.xxx] 归入自身命名空间
          （旧设计把这些键提升到顶层"共享区"，已废弃——所有配置必须归属命名空间）
        """
        inheritable, namespaced = {}, {}
        roots = self.namespace_roots
        for key, value in raw.items():
            # 控制键（dependencies/inherit）不参与合并，直接跳过
            if key in self._CONTROL_KEYS:
                continue
            if key == "hero":
                # hero 是唯一保留的顶层键：局内唯一英雄，任务层横向覆盖英雄层
                inheritable[key] = value
            elif key in roots:
                # 键名命中命名空间根 → 不可继承，保留在命名空间路径下
                namespaced[key] = value
            else:
                # 旧设计的"共享区"已废弃：裸键不再提升到顶层
                raise ConfigurationError(
                    f"顶层裸键 [{key}] 不再支持：请用 [this.{key}] 归入自身命名空间，"
                    f"或用 [hero] 写英雄配置（hero 是唯一保留的顶层键）"
                )
        return inheritable, namespaced
