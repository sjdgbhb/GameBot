# 配置系统

> 源码位置：`src/GameBot/config/`

## 职责

把 `config/data/` 下的 TOML 文件按依赖关系解析、合并成配置字典并应用用户覆盖。
入口一次 `load_task` 拿到完整配置闭包，注入任务类和业务对象。

## 对外能力

- **加载配置**：`config.load_task(name) → dict`，返回依赖闭包合并结果
  （任务、命名空间均可作入参，如 `"kk"`/`"base"`）
- **返回值即唯一真相**：无全局"当前配置"——入口把 dict 注入业务对象；
  工具模块、子进程等拿不到注入的，自行 `load_task`
- **路径解析**：`config.resolve_path(value)` 相对路径 → project_root 绝对路径
- **自动处理**：物品名→ID 解析、快捷键格子注入

## 引擎架构

`src/GameBot/config/system/`，mixin 组合：

| 模块 | 职责 |
|------|------|
| `base.py` | `ConfigurationError` + 常量（`EXCLUSIVE_NAMESPACES`、`CONTROL_KEYS`） |
| `loader.py` | 文件加载缓存、配置名→路径映射、`[this]` 展开、命名空间拆分 |
| `resolver.py` | DFS 后序依赖解析、循环依赖检测、extends 分层约束 |
| `builder.py` | 按加载顺序合并、深度合并、英雄互斥、provenance 记录 |
| `derive.py` | `get_task_view`（任务视图）、`resolve_item_names`（物品名→item_id）、`resolve_bind_cfg`/`force_bind_mode`（bind 调用时选择） |
| `user.py` | `user_configs.json` 加载与覆盖（`_USER_KEY_ROUTES` 路由表） |
| `core.py` | `Config` 单例（纯加载器）：`load_task` / `resolve_path` / `get_provenance` |

## 继承规则

### 1. extends → 线性加载顺序

- `extends = ["war3.jiubing2", "..."]` 声明依赖，DFS 后序展开：依赖在前、自身最后
- 每个文件只加载一次（类似 import），**位置越靠后优先级越高**，同名键深度合并
- 任务/变体文件天然压轴，所以它的字段覆盖一切底层默认

### 2. 段落落点（TOML → dict）

| TOML 写法 | 落点 | 说明 |
|---|---|---|
| `[this]` / `[this.x]` | 文件路径点化 + `.x` | 自身命名空间一律用 `[this]`；`kk.toml` 的 `[this.room]` → `cfg["kk"]["room"]` |
| `[war3]`/`[kk]`/`[hero]`/`[war3.jiubing2.*]` | 对应命名空间路径 | **绝对寻址补丁**：给闭包内其他节点打补丁（如变体 `[kk] bind_mode`）；写**自身**完整路径会被拦截报错 |
| 顶层裸键 | 报错 | 除 `hero` 外无共享区，必须归入命名空间 |
| `hero` | `cfg["hero"]` | 唯一顶层键 |

命名空间根 = 显式注册表 `NAMESPACE_ROOTS`（base/kk/team/war3/web）；
新增任务/英雄/变体文件无需登记，新增一级命名空间才要登记。

### 3. 合并语义

| 节点 | 合并方式 |
|---|---|
| 普通节点 | 深度合并：dict 递归，标量/list 后者整覆盖 |
| `[hero]` | **浅合并**：子键整表覆盖——变体写 `[hero.shard]` 必须写全字段 |
| `heroes.*` | **互斥**：后加载的英雄清除前一英雄全部节点，只留一个 |

### 4. 任务视图 `get_task_view(cfg, task_name)`

沿 extends 链深合并 `war3.jiubing2.tasks.*` 节点（基任务在前、变体在后）：
变体不写的参数自动继承。只合并任务节点——编排任务调子任务参数
用绝对寻址段打到子任务节点，不进任务视图。非任务入参返回空 dict。

## 读取速查

```python
cfg = config.load_task("war3.jiubing2.tasks.endless.endless_善木木")
war3_cfg, kk_cfg, hero_cfg = cfg["war3"], cfg["kk"], cfg["hero"]   # 注入业务对象
task_cfg = get_task_view(cfg, task_name)      # 任务自身参数（extends 链合并）
bind_cfg = resolve_bind_cfg(kk_cfg)           # 按 ns.bind_mode 选前/后台参数表
```

定位某个值在哪个节点、被谁覆盖：用下文 `dump`/`explain`/`order` CLI。

## 调用规范

- ✅ `main()` 调 `load_task` **一次**，返回 dict 注入任务类构造函数，再分发到业务对象
- ✅ 原子任务由上层注入 `combat.cfg`（完整闭包）和自身配置段
- ❌ 业务代码/任务类 `__init__`/顶层调度器禁止 `load_task` 和直接索引原始配置
- ✅ 例外：拿不到注入的工具模块（推理客户端、dm_bridge 子进程）自行 `load_task(<命名空间>)`

## 关键约束

- `user_configs.json` 覆盖英雄背包、目标物品、巡逻轮数等用户可调参数（mtime 变化缓存失效）
- extends 分层约束（告警阶段）：低层文件不得 extends `tasks.*`；task→task 允许
- `name`/`extends` 是文件级控制键，不参与合并；`dependencies` 已废弃报错
- 绑定参数不预写 `ns.bind` 派生字段，调用点 `resolve_bind_cfg(ns_cfg)` 实时选表；
  组队多成员强转后台 `force_bind_mode(cfg, "background")`
- 配置值不要硬编码进代码；物品快捷键从 `hero.inventory` 取

## 排障工具（CLI）

```bash
python -m GameBot.config order <配置名>                  # 依赖闭包线性加载顺序
python -m GameBot.config explain <配置名> <dot路径>      # 键的值与写入来源链
python -m GameBot.config dump <配置名> [--out f.json] [--annotate]  # 导出合并结果
python -m GameBot.config lint                            # 结构校验全部 TOML
python -m GameBot.config new <配置名>                    # 生成任务/变体模板
```

provenance 来源名：TOML 配置名 / `user_configs.json` / `<派生:xxx>`（inventory_slots 注入、物品名→item_id）。
代码侧：`config.get_provenance(task_name)` → `{dot_path: [来源链]}`。

## 关联文档

- [新增英雄配置](../guides/new-hero.md)
- [新增任务](../guides/new-task.md)
- [大漠插件绑定模式](../domain/dm-plugin.md)
