# claim-registry Specification

## Purpose

同机多个 GameBot 脚本实例间的共享认领注册表：以机器级 JSON 文件 + 命名互斥锁维护
"存活实例 → 玩家 → KK 进程 → 已认领窗口"映射，使各脚本无需重复侵入式识别即可协调窗口归属。

## Requirements

### Requirement: 脚本实例注册

系统 SHALL 在每个脚本实例首次参与认领流程时将其注册进机器级共享注册表，记录脚本
PID、`target_player` 与任务名。注册表位于固定的机器级路径，同一台机器上不同安装
目录的实例 MUST 共享同一注册表文件。

#### Scenario: 实例首次注册

- **WHEN** 脚本实例首次调用认领相关接口
- **THEN** 注册表 instances 表新增该实例条目（脚本 PID、target_player、任务名、注册时间）

#### Scenario: 死实例读时剪枝

- **WHEN** 任一实例读取注册表时某条 instance 记录对应的 PID 已不存活
- **THEN** 该条目被视为无效并从注册表中移除，不影响其曾认领窗口的归属判定逻辑之外的解读

### Requirement: 重复玩家实例拒绝

系统 SHALL 在注册阶段拒绝与存活实例具有相同非空 `target_player` 的新实例，新实例
MUST 报错退出而非继续运行。

#### Scenario: 重复玩家被拒

- **WHEN** 新实例注册时注册表已存在相同 `target_player` 且 PID 存活的实例
- **THEN** 新实例报错退出，不进入任务主流程

#### Scenario: 死实例不阻挡同名玩家

- **WHEN** 注册表中存在相同 `target_player` 但 PID 已死亡的实例记录
- **THEN** 新实例正常注册，旧条目被剪枝

### Requirement: KK 进程归属映射

系统 SHALL 维护 `kk_pid → player` 映射，由首次识别出该 KK 进程归属的实例写入，其后
所有实例直接读取共享。每个条目 MUST 记录 KK 进程创建时间，读取时以"进程存活 +
启动时间一致"校验有效性。

#### Scenario: 映射一次写入全员共享

- **WHEN** 某实例通过自举识别确认 kk_pid 属于玩家 P 并写入注册表
- **THEN** 其他实例读取该条目后直接获知归属，无需再次对窗口做侵入式识别

#### Scenario: PID 复用防错认

- **WHEN** 注册表中 kk_pid 条目对应的进程存活但启动时间与记录不一致
- **THEN** 该条目被视为失效，归属判定按"未知"处理并可被重新识别写入

### Requirement: 已认领窗口归属记录

系统 SHALL 记录已认领窗口的归属：`kind:hwnd → kk_pid`。条目有效性 MUST 以窗口存活
（IsWindow）且归属关系可复算一致为前提（war3 窗口按其进程直接父 PID 复核，KK 窗口
按窗口 PID 复核）；复核不一致或窗口已销毁时条目失效。

#### Scenario: 窗口销毁后条目失效

- **WHEN** 注册表中记录的 hwnd 已不存在（IsWindow 为假）
- **THEN** 该条目不再参与归属判定，可被新窗口记录覆盖

#### Scenario: 归属关系复核

- **WHEN** 读取 `war3:<hwnd>` 条目时，该窗口存活但其进程的直接父 PID 与记录不符
- **THEN** 该条目失效，归属按"未知"处理

### Requirement: 并发守护与原子写

系统 SHALL 用全局命名互斥锁守护注册表的读-改-写全过程，并以临时文件 + 原子替换
方式落盘。注册表文件损坏或缺失时 MUST 视为空注册表并记录告警，不得使脚本崩溃。

#### Scenario: 并发读写不撕裂

- **WHEN** 两个实例同时更新注册表
- **THEN** 写操作串行执行，读到的永远是一份完整一致的 JSON

#### Scenario: 注册表损坏自愈

- **WHEN** 注册表文件内容非法（截断/非 JSON）
- **THEN** 系统记录告警并按空注册表继续工作，下次写回后恢复正常
