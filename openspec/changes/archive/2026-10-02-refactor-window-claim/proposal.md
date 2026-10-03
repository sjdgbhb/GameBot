# Proposal

## Why

多开窗口认领目前是三套各自为政的协议（war3 逐窗 token、KK 房间 token、KK 大厅下拉框 OCR），
识别全靠侵入式操作（绑定窗口 + 发聊天 token + OCR），串行在全局锁内，单次认领动辄数秒到
数十秒且易因 OCR 抖动出错。已实机验证 `ppid(war3_pid) == 房间 owner_pid`（war3 是开房
KK 客户端的直接子进程），同机各脚本进程间可以用注册表共享"玩家 → KK 进程 → 窗口"映射，
把认领从"逐窗侵入式识别"降为"枚举 + 进程表查表 + 互斥锁"的毫秒级只读操作。

## What Changes

- 新增机器级共享注册表（`%LOCALAPPDATA%\GameBot\claim_registry.json` + `NamedMutex` 守护）：
  脚本实例注册（存活 pid 剪枝、重复 `target_player` 拒绝启动）、`kk_pid → player` 归属映射
  （进程创建时间戳防 pid 复用）、已认领窗口记录（hwnd 活性校验）。
- 新增统一认领原语：枚举候选 → per-hwnd 互斥锁 → 查表定归属 → 匹配持有 / 不匹配释放 →
  超时抛 `ClaimError` 终止任务。war3 / KK 房间 / KK 大厅收敛到同一骨架，全局认领串行锁退役。
- **BREAKING**：war3 归属判定改为 `ppid(war3_pid) == kk_pid` 直接父进程比对，任意游戏阶段
  可用；"必须在加载页认领"约束及分阶段回调（`_identify_claim_window`）整体移除。
- **BREAKING**：自举按脚本启动场景分派且不回退——大厅启动走大厅下拉框 OCR，房间启动走
  房间聊天 token，游戏内启动走 war3 聊天 token；各自失败即终止任务。
- 新增单开快速路径：存活实例数 == 1 且候选窗口唯一时跳过归属识别直接认领，但仍持有
  per-hwnd 互斥锁并写注册表（防晚加入脚本抢占同一窗口）。
- 重启秒认：注册表命中 `player → kk_pid` 且进程活性校验通过时直接采用，跳过一切识别。
- 删除过时代码：`identify_war3_owner`/`find_target_war3_hwnd`/`bind_war3_window`、
  `hall_owner_cache` 死接口、全局认领锁、`mismatched` 黑名单、`loading_page` 配置段、
  任务层重复的 `_claim_kk_room` 胶水。

## Capabilities

### New Capabilities

- `claim-registry`: 同机多脚本实例的共享认领注册表——实例注册与重复玩家拒绝、
  kk_pid→player 归属映射、已认领窗口记录、句柄/PID 活性与启动时间校验、并发读写守护。
- `window-claim`: 统一的窗口认领协议——场景化自举（大厅/房间/游戏内）、PID/PPID 只读归属
  判定、per-hwnd 互斥锁占用、单开快速路径、认领失败终止语义。

### Modified Capabilities

（无——项目当前无既有 specs）

## Impact

- **环境**：全部改动在主环境 `.venv`（业务层 + 驱动层）；`.venv-dm` 不受影响。
  不触碰大漠 dx 截图禁令与双环境隔离约束——新认领路径为纯 Win32 API 只读调用
  （`GetWindowThreadProcessId`/`Toolhelp32`/`IsWindow`）+ NamedMutex + 文件 IO。
- **代码**：新增 `runner/driver/claim_registry.py`、`runner/business/claim.py`；
  重写 `business/war3/window_manager.py` 认领段、`business/kk/multi_instance.py`、
  `business/kk/hall_manager.py` 认领段；精简 `tasks/.../endless.py`、`game_count.py` 等
  任务层认领胶水。
- **配置**：`kk.toml [this.multi_instance]` 保留房间 token 坐标；`war3.toml
  [this.multi_instance]` 保留聊天 token 配置、删除 `loading_page` 段；新增注册表路径/
  超时配置项。
- **测试**：`tests/unit/test_multi_instance.py`、`test_hall_manager.py`、
  `test_endless_task_boss_timeout.py`、相关集成测试需按新协议重写。
- **文档**：`AGENTS.md` 多开用法段、`docs/` 相关模块卡片需同步更新。
- **回滚思路**：变更集中在认领链路，旧实现留在 git 历史；如线上回归可回退 commit。
  注册表文件为纯新增，删除即回到无共享状态。
