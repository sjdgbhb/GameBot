# 升级圣痕任务

## 基本信息

- **类名**：`UpgradeStigmataTask`
- **源码**：`src/GameBot/runner/tasks/war3/jiubing2/others/upgrade_stigmata.py`
- **配置**：`config/data/war3/jiubing2/tasks/others/upgrade_stigmata.toml`
- **运行命令**：`uv run python -m GameBot.runner.tasks.war3.jiubing2.others.upgrade_stigmata`
- **依赖**：`war3.jiubing2.tasks.atomic.blackstone_gate_harassment`
  （默认英雄由原子任务链带入；可用 `user_configs.json` 的 hero 字段或变体覆盖）
- **继承**：`AtomicLoopTask`
- **多开变体**：`upgrade_stigmata_<玩家名>.toml`（`[this] target_player` +
  `[war3]`/`[kk]` `bind_mode="background"`），启动
  `... others.upgrade_stigmata upgrade_stigmata_善木木`；认领失败任务直接停止

## 功能

每完成一次城门骚扰任务获得一次圣痕升级机会（机会不可叠加），故采用"城门骚扰 → 走到圣痕 NPC → 升级一次"交替循环，直至所有待升级词条达标。

## 流程

1. 绑定窗口，预热 OCR，启动 `TextMonitor` 常驻监测
2. 交替循环：
   - **城门骚扰**：执行一次 `GateHarassmentTask` 获取升级机会
     （接取被拒且提示"已经接取"时，自动 -rw 放弃遗留任务、等待冷却后重接）
   - **圣痕升级**：
     - 走到圣痕 NPC（小地图导航）
     - 点击选中 NPC（技能板翻页重置为第 1 页）
     - F2 打开圣痕面板，OCR 读取各词条当前数值（仅成功/不确定时重读；
       升级失败数值未变，复用上次面板数据跳过读面板）
     - 若目标词条在第 2 页，先点翻页按钮
     - 点击对应技能格（列 = 词条在面板中的序号）
     - OCR 检测"成功"/"失败"提示
3. 所有 `term_limit` 内词条达上限时结束

## 词条解析与选择

- 圣痕面板每个位置（上位/核心/中位/下位）的词条列表**保留全部词条**
  （含未配置上限的占位词条），顺序即面板显示顺序、与圣痕 NPC 技能板
  列号一致——索引错位会导致点错格子
- 词条名归一化：按 `term_limit` 键的子串匹配（"力量属性"→"力量"），
  未命中保留原名占位；分隔符在而数字缺失（行尾被 OCR 裁掉）时记为
  `None` 占位，维持索引对齐
- 每次选择 `term_limit` 内**差距最大**的未达上限词条升级

## 关键配置

| 配置项 | 说明 |
|--------|------|
| `term_limit` | 词条上限表（jiubing2.toml `[this.stigmata.term_limit]`），未配置的词条仅占位不升级 |
| `combat_mode` | 战斗模式：`auto_attack`（全程平A）/ `cast_skills`（自动施法） |
| `success_text` / `fail_text` | 升级成功/失败提示文本 |
| `result_timeout` / `result_check_interval` | 升级结果检测超时 / 回退检测间隔 |
| `loop_interval_time` | 循环间隔时间（秒） |
| `clear_nearby_probability` | 路线点清理附近物品概率（0~1） |
| `points` | 2 个路线点：城门骚扰完成→圣痕 NPC、升级后→返回守卫队长 |
| `term_short` / `pos_labels` | 浮窗显示用词条缩写 / 位置标签 |
