# Spec Delta

## Purpose

多开/单开场景下脚本对 war3 与 KK 窗口的独占认领：按脚本启动场景做一次身份自举
建立 `player → kk_pid` 映射，此后所有窗口认领均以只读 PID/PPID 判定 + 命名互斥锁
完成，认领失败即终止对应任务。

## ADDED Requirements

### Requirement: 场景化身份自举

系统 SHALL 按脚本启动时账号所处场景执行唯一对应的自举识别，场景间 MUST NOT 回退：

- 账号在 KK 大厅：大厅窗口下拉框 OCR 识别玩家 ID，命中 `target_player` 的窗口所属
  进程即本账号 kk_pid
- 账号在 KK 房间：向房间聊天输入框发送随机 token，OCR 聊天记录"玩家名：token"
  提取归属，命中窗口所属进程即本账号 kk_pid
- 账号已在 war3 游戏内：向 war3 窗口发送聊天 token，OCR 聊天区判定归属；认领成功
  后由 `ppid(war3_pid)` 推出 kk_pid

自举识别失败 MUST 终止对应脚本任务。自举前 MUST 先查注册表 `player → kk_pid` 映射，
命中且进程活性校验通过时直接采用，跳过一切识别。

#### Scenario: 房间启动自举

- **WHEN** 以房间场景启动的脚本执行自举
- **THEN** 仅走房间聊天 token 识别；超时未命中任何房间窗口 → 任务终止

#### Scenario: 大厅启动自举

- **WHEN** 以大厅场景启动的脚本执行自举
- **THEN** 仅走大厅下拉框 OCR 识别；未识别到归属 `target_player` 的大厅 → 任务终止

#### Scenario: 游戏内启动自举

- **WHEN** 以游戏内场景启动的脚本执行自举
- **THEN** 仅走 war3 聊天 token 识别；超时未命中 → 任务终止

#### Scenario: 注册表命中跳过自举

- **WHEN** 脚本执行自举时注册表中本 `target_player` 已有 kk_pid 记录且该进程存活、
  启动时间一致
- **THEN** 直接采用该 kk_pid，不做任何窗口识别操作

### Requirement: war3 窗口归属判定（直接父进程）

系统 SHALL 以"war3 窗口进程的直接父 PID 等于本账号 kk_pid"判定 war3 窗口归属。
判定为纯只读操作（枚举 + 进程信息查询），MUST NOT 对窗口做绑定、改尺寸或输入注入，
因此任意游戏阶段（读图/难度/游戏内）均可执行，无认领时机约束。

#### Scenario: 父进程匹配即归属

- **WHEN** 候选 war3 窗口的 `ppid(get_window_process_id(hwnd))` 等于本脚本 kk_pid
- **THEN** 该窗口判定为本账号窗口，可进入互斥锁认领

#### Scenario: 读图期零操作认领

- **WHEN** war3 窗口处于地图加载页时执行认领
- **THEN** 归属判定完成过程中窗口未被绑定、未改尺寸、未注入输入，加载进程不受干扰

#### Scenario: 父进程不匹配跳过

- **WHEN** 候选 war3 窗口的直接父 PID 不等于本脚本 kk_pid
- **THEN** 跳过该窗口且不向其发送任何输入，继续检查下一候选

### Requirement: KK 窗口归属判定（PID 匹配）

系统 SHALL 以"KK 窗口所属进程 PID 等于本账号 kk_pid"判定 KK 侧窗口（大厅、房间、
弹窗、掉线框等）归属，无需再对该窗口做 OCR 或 token 识别。

#### Scenario: PID 匹配即归属

- **WHEN** 本脚本已知 kk_pid，枚举到某 KK 房间窗口其 `get_window_process_id(hwnd)`
  等于 kk_pid
- **THEN** 该房间判定为本账号房间，可进入互斥锁认领

### Requirement: per-hwnd 互斥锁独占

系统 SHALL 在认领窗口前按句柄获取命名互斥锁，获取失败的窗口视为已被其他脚本占用，
MUST 跳过且不触碰。认领成功后互斥锁持有至显式释放或进程退出（崩溃自动释放）。

#### Scenario: 已被认领的窗口跳过

- **WHEN** 候选窗口的命名互斥锁 try_acquire 失败
- **THEN** 跳过该窗口继续下一候选，不向其发 token/OCR/输入

#### Scenario: 复用已认领窗口

- **WHEN** 本脚本已认领的窗口句柄仍存活且注册表归属复核一致
- **THEN** 直接复用该句柄返回，不重新枚举与判定

### Requirement: 单开快速路径

系统 SHALL 在注册表存活实例数为 1 且该窗口类型候选数恰为 1 时跳过归属识别，直接
认领该候选窗口；快速路径 MUST 仍持有 per-hwnd 互斥锁并完成注册表登记。候选数大于
1 时 MUST 回到完整归属判定协议。

#### Scenario: 单开直接认领

- **WHEN** 本机仅本脚本存活且该类窗口唯一候选
- **THEN** 不执行任何识别操作，直接持锁认领该窗口

#### Scenario: 多候选退回完整协议

- **WHEN** 存活实例数为 1 但同类候选窗口数大于 1
- **THEN** 按完整归属判定协议逐个验证，不误取非本账号窗口

### Requirement: 认领失败终止任务

系统 SHALL 在认领超时耗尽后抛出认领失败异常，调用方任务 MUST 终止而非继续运行。
归属未确认时 MUST NOT 对任何候选窗口执行退出键清场等破坏性操作。

#### Scenario: 超时抛错终止

- **WHEN** 认领循环在 claim_timeout 内未认领到归属窗口
- **THEN** 抛出认领失败异常，任务终止并记录失败原因（候选数、占用情况）

### Requirement: 每局窗口复领

系统 SHALL 支持多局任务中 war3 窗口销毁后释放旧认领并在下一局重新认领；因
kk_pid 不变，复领 MUST 仅依赖 PPID 判定与注册表，不做任何重新识别。

#### Scenario: 局间复领

- **WHEN** 上一局 war3 窗口销毁、新局 war3 窗口出现且其父 PID 为本账号 kk_pid
- **THEN** 直接经 PPID 匹配认领新窗口，耗时为纯进程表查询级别
