# 声望任务

## 每日声望

- **类名**：`DailyReputationTask`
- **源码**：`src/GameBot/tasks/reputation/daily_reputation.py`
- **配置**：`config/data/tasks/reputation/daily_reputation.toml`
- **运行命令**：`uv run python -m GameBot.tasks.reputation.daily_reputation`
- **依赖**：`tasks.blackstone_reputation` + `tasks.forest_reputation` + `scenes.menethil` + `scenes.palace` + `heroes.paladin`

### 功能

顺序编排：黑石城声望（城门骚扰 ×N）→ 转场至森之城 → 森之城声望（迅猛野兽 ×N），各 150 点。

### 流程

1. 执行 `BlackstoneReputationTask.run()`（内部自行绑定窗口与循环）
2. 转场：使用传送卷（paladin 物品 id=5）传送至远古森林外围入口 → 走进传送圈进入森之城
3. 执行 `ForestReputationTask.run()`

## 黑石城声望

- **类名**：`BlackstoneReputationTask`
- **源码**：`src/GameBot/tasks/reputation/blackstone_reputation.py`
- **配置**：`config/data/tasks/reputation/blackstone_reputation.toml`
- **运行命令**：`uv run python -m GameBot.tasks.reputation.blackstone_reputation`
- **依赖**：`tasks.atomic.blackstone_gate_harassment`（间接依赖黑石城场景）
- **继承**：`ReputationTask` → `AtomicLoopTask`

### 功能

每日声望上限 150，每次城门骚扰 +5 声望。按 `target_reputation / reputation_per_run` 反推需完成次数，循环执行城门骚扰原子任务。

## 森之城声望

- **类名**：`ForestReputationTask`
- **源码**：`src/GameBot/tasks/reputation/forest_reputation.py`
- **配置**：`config/data/tasks/reputation/forest_reputation.toml`
- **运行命令**：`uv run python -m GameBot.tasks.reputation.forest_reputation`
- **依赖**：`tasks.atomic.swift_beast`（间接依赖森之城场景）
- **继承**：`ReputationTask` → `AtomicLoopTask`

### 功能

每日声望上限 150，每次迅猛野兽 +10 声望。按 `target_reputation / reputation_per_run` 反推需完成次数，循环执行迅猛野兽原子任务。

## 关键配置

| 配置项 | 说明 |
|--------|------|
| `target_reputation` | 声望上限（默认 150） |
| `reputation_per_run` | 每次任务获得的声望（黑石城 5 / 森之城 10） |
| `loop_interval_time` | 循环间隔时间 |

## 继承关系

```
AtomicLoopTask（基类：窗口绑定、OCR 预热、原子任务循环）
└── ReputationTask（增加声望上限反推次数）
    ├── BlackstoneReputationTask
    └── ForestReputationTask

DailyReputationTask（独立编排类，组合黑石城 + 森之城 + 转场）
```
