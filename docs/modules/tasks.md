# 任务编排层

> 源码位置：`src/GameBot/runner/tasks/` + `src/GameBot/runner/ui/`

## 职责

任务编排层把业务原语组装成完整的任务流程，控制循环、展示进度、响应停止。
它是用户直接交互的层：每个任务模块都有独立的 `main()` 入口，可通过 CLI 或 Web 启动。

包含两部分：
- **任务编排**（`runner/tasks/`）：任务基类、原子任务、各类具体任务
- **脚本控制UI**（`runner/ui/`）：浮窗、显示器监听

## 对外能力

### 任务编排
- **任务基类**：提供循环执行原子任务的通用骨架
  - 自动装配大漠客户端、业务对象、绑定窗口、预热OCR、启动文字监测
  - 循环调用原子任务，支持进度展示和停止
- **原子任务**：「走到NPC→接任务→沿路线行动→OCR检测完成→回NPC提交」的最小可复用单元，如城门骚扰、迅猛野兽
- **声望任务**：在原子任务循环基础上，按声望上限/每次收益反推循环次数
- **多原子任务**：一次接取多个原子任务，走共享路线，依次提交
- **具体任务**：无尽（多局/单局）、钓鱼、巡逻拾取、升级圣痕、每日声望、个人成就

### 脚本控制UI
- **浮窗**：tkinter 置顶悬浮窗，显示倒计时和运行进度，支持单行/多行进度
- **停止键**：浮窗运行时监听小键盘减号作为停止键

## 依赖关系

- **业务逻辑层**：War3Business / GameUI / CombatHelper / SceneNavigator / EndlessRunner
- **推理模块**：OCR 预热
- **配置系统**：通过 `load_task` 获取配置闭包
- **共享工具**：日志、异常（StopTaskError 等）
- **UI层**：浮窗入口包装

## 任务继承体系

```
AtomicLoopTask（基类：窗口绑定、OCR预热、原子任务循环）
├── UpgradeStigmataTask     # 升级圣痕（交替：城门骚扰 + 圣痕升级）
└── PersonalAchievementTask  # 个人成就（继承多原子任务基类）

ReputationTask（继承原子循环基类，增加声望上限反推次数）
├── BlackstoneReputationTask  # 黑石城声望
└── ForestReputationTask      # 森之城声望

DailyReputationTask（独立编排类，组合黑石城 + 森之城声望，不继承 ReputationTask）

EndlessTask / EndlessSingleTask（独立类，不继承原子循环基类）
FishingTask / PatrolLootTask（独立类）
```

## 任务入口模式

所有任务模块遵循统一模式：

```
main() 入口
  → setup_global_exception_hook()        # 安装全局异常钩子
  → config.load_task("war3.jiubing2.tasks.{类别}.xxx")  # 唯一一次加载配置
  → 构造任务类（注入配置dict）
  → run_with_float_window(task.run)      # 浮窗包装启动
    → 倒计时 → 后台线程运行任务 → 主线程显示浮窗 → 停止键中断
```

CLI 入口（`main.py`）维护任务名到配置路径和任务类的映射表，
Web 入口通过推导模块路径直接启动任务子进程，两者都调用 `load_task`。

## 关键约束

### 原子任务调度
- 上层任务通过统一的调度方法调用原子任务
- 原子任务不接受完整配置闭包，而是接受已拆分的业务对象和配置段
- 原子任务通过战斗辅助对象访问完整依赖闭包（如 scenes 命名空间下的 NPC 配置）

### 进度展示
- 浮窗支持单行进度（如「第3/10局」）和多行进度（如每日声望显示两个城市进度）
- 进度通过回调函数更新，任务类在循环中调用回调

### 停止机制
- 浮窗停止键触发 `stop_event`
- 业务操作的等待会检查 `stop_event`，被中断时抛出 `StopTaskError`
- 任务循环捕获 `StopTaskError` 后优雅停止

## 配置约定

任务配置位于 `config/data/war3/jiubing2/tasks/` 下，按类别分目录：
- `atomic/` — 原子任务（迅猛野兽/城门骚扰/毒蛇/蛇蛋/小炎蛇）
- `endless/` — 无尽任务（多局/单局）
- `others/` — 其他任务（钓鱼/巡逻拾取/升级圣痕）
- `reputation/` — 声望任务（每日/黑石城/森之城）
- `achievements/` — 成就任务（个人）

每个任务 TOML 通过 `name` 声明自身命名空间，并通过 `extends` 声明继承（通常包含 `war3.jiubing2`、`heroes.xxx` 和 `scenes.xxx`）。任务数据写在 `[this]` 下。

## 禁忌

- ❌ 不要在任务类 `__init__` 中调用 `load_task`（在 `main()` 中调用）
- ❌ 不要在任务类中直接操作大漠 COM（通过业务对象）
- ❌ 不要在任务类中硬编码循环次数（声望任务从配置反推，其他从配置读取）
- ❌ 不要忘记用 `run_with_float_window` 包装任务入口（否则无法停止）

## 关联文档

- [业务逻辑层](business.md) —— 任务编排依赖的业务原语
- [配置系统](config.md) —— 任务配置的加载机制
- [组队框架](team.md) —— 组队任务的独立框架
- [任务详细文档](../tasks/) —— 各任务的详细流程说明
- [新增任务模块](../guides/new-task.md) —— 如何添加新任务
