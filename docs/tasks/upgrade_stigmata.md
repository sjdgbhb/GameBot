# 升级圣痕任务

## 基本信息

- **类名**：`UpgradeStigmataTask`
- **源码**：`src/GameBot/tasks/others/upgrade_stigmata.py`
- **配置**：`config/data/tasks/others/upgrade_stigmata.toml`
- **运行命令**：`uv run python -m GameBot.tasks.others.upgrade_stigmata`
- **依赖**：`tasks.atomic.blackstone_gate_harassment`（间接依赖黑石城场景）
- **继承**：`AtomicLoopTask`

## 功能

每完成一次城门骚扰任务获得一次圣痕升级机会（机会不可叠加），故采用"城门骚扰 → 走到圣痕 NPC → 升级一次"交替循环，直至所有待升级词条达标。

## 流程

1. 绑定窗口，预热 OCR，启动 `TextMonitor` 常驻监测
2. 交替循环：
   - **城门骚扰**：执行一次 `GateHarassmentTask` 获取升级机会
   - **圣痕升级**：
     - 走到圣痕 NPC（小地图导航）
     - 点击选中 NPC（技能板翻页重置为第 1 页）
     - 若目标词条在第 2 页，先点翻页按钮
     - 点击对应技能格（列 = 词条索引 + 1）
     - OCR 检测"成功"/"失败"提示
     - 成功：按期望增益 `mean[idx]` 递减剩余点数
     - 失败：机会已消耗
     - 无提示：该词条视为已升满，置 0 不再升级
3. 所有词条剩余点数为 0 时结束

## 关键配置

| 配置项 | 说明 |
|--------|------|
| `upgrade_config` | 待升级词条配置：`{upper: [v1, v2], core: [...], ...}` |
| `mean` | 单次成功期望增益：`[1, 1, 1]` |
| `success_text` | 升级成功提示文本（默认"成功"） |
| `fail_text` | 升级失败提示文本（默认"失败"） |
| `return_walk_time` | 从圣痕 NPC 返回守卫队长的行走时间 |
| `loop_interval_time` | 循环间隔时间 |
| `result_timeout` | 升级结果检测超时（秒） |

## 词条选择策略

每次选择剩余点数最多的词条升级，优先级顺序：`upper` → `core` → `middle` → `lower`。
