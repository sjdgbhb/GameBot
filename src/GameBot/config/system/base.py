"""配置系统基础设施 — ConfigurationError 异常和 Config 类的常量。"""


class ConfigurationError(Exception):
    """配置系统异常 — 文件缺失、循环依赖、格式错误等。"""

    pass


# 一级命名空间注册表：config/data/ 下的一级领域名（显式登记，不随目录扫描变化）。
# 新增任务/英雄/场景/变体文件无需改这里（都在 war3 根内）；
# 只有新增一级命名空间（如 data/yy/）才加一行——这本该是显式决策。
# 自动扫描的风险：data/ 下任何新建目录都会把同名裸键从"可继承"翻转为
# "命名空间隔离"，无报错、静默改变合并语义。
NAMESPACE_ROOTS = frozenset({"base", "kk", "team", "war3", "web"})

# 互斥命名空间：一场游戏只能玩一个英雄，heroes.* 中最后加载者独占生效（规则 3）
# 当加载顺序中出现多个 heroes.* 配置时，后加载的英雄整体替换前一英雄的可继承节点
EXCLUSIVE_NAMESPACES = frozenset({"war3.jiubing2.heroes"})

# 文件级控制键，不参与合并结果
# - extends: 声明依赖列表，解析完即丢弃
# - name: 层的显式名称（可选，默认等于配置点路径）
CONTROL_KEYS = frozenset({"extends", "name"})
