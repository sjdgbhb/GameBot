"""依赖解析 — DFS 后序展开依赖树、循环依赖检测。"""

from typing import List, Set

from .base import ConfigurationError


class ConfigResolverMixin:
    """Config 的依赖解析 mixin。

    依赖 self._load_file()（ConfigLoaderMixin 提供）。
    """

    def _resolve_order(self, config_name: str, order: List[str], visiting: List[str], visited: Set[str]):
        """深度优先后序解析依赖，展开为线性加载顺序（规则 1）。

        依赖在前、自身在后；每个文件只出现一次（首次到达的位置生效），
        因此顺序靠后的配置覆盖靠前的。

        :param config_name: 配置名（如 "jiubing2", "tasks.patrol_loot"）
        :param order: 输出的加载顺序列表（原地追加）
        :param visiting: 当前 DFS 栈（用于循环依赖检测）
        :param visited: 已解析完成的配置名集合
        """
        # 已解析过的配置不再重复处理（类似 Python import 的去重）
        if config_name in visited:
            return
        # 在当前 DFS 栈中再次出现 → 循环依赖
        if config_name in visiting:
            chain = " -> ".join(visiting + [config_name])
            raise ConfigurationError(f"循环依赖: {chain}")
        visiting.append(config_name)
        raw = self._load_file(config_name)
        # 递归解析所有依赖，依赖在前、自身在后（后序）
        for dep_name in raw.get("dependencies", []):
            self._resolve_order(dep_name, order, visiting, visited)
        visiting.pop()
        visited.add(config_name)
        # 自身最后加入，因此加载顺序中后面的配置覆盖前面的
        order.append(config_name)
