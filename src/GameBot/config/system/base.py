"""配置系统基础设施 — ConfigurationError 异常和 Config 类的常量。"""


class ConfigurationError(Exception):
    """配置系统异常 — 文件缺失、循环依赖、格式错误等。"""

    pass


# 互斥命名空间：一场游戏只能玩一个英雄，heroes.* 中最后加载者独占生效（规则 3）
# 当加载顺序中出现多个 heroes.* 配置时，后加载的英雄整体替换前一英雄的可继承节点
EXCLUSIVE_NAMESPACES = frozenset({"war3.jiubing2.heroes"})

# 文件级控制键，不参与合并结果
# - extends: 声明依赖列表，解析完即丢弃
# - name: 层的显式名称（可选，默认等于配置点路径）
CONTROL_KEYS = frozenset({"extends", "name"})
