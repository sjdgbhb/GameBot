# 声望任务

## 每日声望

- **类名**：`DailyReputationTask`
- **源码**：`src/GameBot/runner/tasks/war3/jiubing2/reputation/daily_reputation.py`
- **配置**：`config/data/war3/jiubing2/tasks/reputation/daily_reputation.toml`
  （黑石城/森之城子配置在 `[this.blackstone]` / `[this.forest]` 段，无独立 toml）
- **运行命令**：`uv run python -m GameBot.runner.tasks.war3.jiubing2.reputation.daily_reputation`
- **依赖**：`war3.jiubing2.tasks.atomic.blackstone_gate_harassment` +
  `war3.jiubing2.tasks.atomic.swift_beast` + `war3.jiubing2.scenes.menethil` + `kk`

### 功能

顺序编排：黑石城声望（城门骚扰 ×N）→ 转场至森之城 → 森之城声望（迅猛野兽 ×N），各 150 点。
`enable_blackstone` / `enable_forest` 可分别开关两段。

### 流程

1. 执行 `BlackstoneReputationTask.run()`（内部自行绑定窗口与循环）
2. 转场：使用传送卷（hero 物品栏「远古森林外围入口传送卷轴」）传送至
   远古森林外围入口 → 走进传送圈进入森之城（封装在 `ForestReputationTask._travel_to_forest_city`）
3. 执行 `ForestReputationTask.run()`

## 黑石城声望

- **类名**：`BlackstoneReputationTask`
- **源码**：`src/GameBot/runner/tasks/war3/jiubing2/reputation/blackstone_reputation.py`
- **配置**：`daily_reputation.toml` 的 `[this.blackstone]` 段
- **运行命令**：`uv run python -m GameBot.runner.tasks.war3.jiubing2.reputation.blackstone_reputation`
- **依赖**：`war3.jiubing2.tasks.atomic.blackstone_gate_harassment`（间接依赖黑石城场景）
- **继承**：`ReputationTask` → `AtomicLoopTask`

### 功能

每日声望上限 150，每次城门骚扰 +5 声望。按 `target_reputation / reputation_per_run` 反推需完成次数，循环执行城门骚扰原子任务。

## 森之城声望

- **类名**：`ForestReputationTask`
- **源码**：`src/GameBot/runner/tasks/war3/jiubing2/reputation/forest_reputation.py`
- **配置**：`daily_reputation.toml` 的 `[this.forest]` 段
- **运行命令**：`uv run python -m GameBot.runner.tasks.war3.jiubing2.reputation.forest_reputation`
- **依赖**：`war3.jiubing2.tasks.atomic.swift_beast`（间接依赖森之城场景）
- **继承**：`ReputationTask` → `AtomicLoopTask`

### 功能

每日声望上限 150，每次迅猛野兽 +10 声望。按 `target_reputation / reputation_per_run` 反推需完成次数，循环执行迅猛野兽原子任务。

## 关键配置

| 配置项 | 说明 |
|--------|------|
| `enable_blackstone` / `enable_forest` | 是否执行黑石城 / 森之城声望段 |
| `[this.blackstone]` / `[this.forest]` | 子任务段：`progress_label` / `target_reputation` / `reputation_per_run` / `loop_interval_time` |
| `target_reputation` | 声望上限（默认 150） |
| `reputation_per_run` | 每次任务获得的声望（黑石城 5 / 森之城 10） |
| `loop_interval_time` | 循环间隔时间（森之城默认 50s，对齐迅猛野兽刷新） |
| `clear_nearby_probability` | 每个路线点清理附近物品的概率（子任务共用） |

> 绑定模式：原子任务 `blackstone_gate_harassment` 把 `war3`/`kk` 补丁成
> `background`；`daily_reputation.toml` 用 `[war3]`/`[kk]` 段改回 `foreground`
> （后加载覆盖）。改模式时直接改这两个段。

## 继承关系

```
AtomicLoopTask（基类：窗口绑定、OCR 预热、原子任务循环）
└── ReputationTask（增加声望上限反推次数）
    ├── BlackstoneReputationTask
    └── ForestReputationTask

DailyReputationTask（独立编排类，组合黑石城 + 森之城 + 转场）
```
