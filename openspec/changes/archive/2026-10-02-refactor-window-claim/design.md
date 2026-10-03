# Design

## Context

现状见 proposal.md。关键已验证事实（AGENTS.md「KK ↔ war3 进程/窗口关系」）：

- war3.exe 是开房 KK 客户端（Platform.exe）的**直接子进程**：`ppid(war3_pid) == owner_pid`；
  多开时各账号客户端由 KK 主实例派生（主实例 ← 客户端 ← war3），故只能用直接父进程
  比对，不能用祖先链包含匹配。
- 窗口层无任何隶属关系；开局后该客户端的大厅/房间窗口被移到 (-32000,-32000) 屏外，
  仍可枚举可绑定，但房间 UI 置灰不可操作。
- 窗口生命周期内 hwnd、war3 进程 PID、父子关系不变（用户确认）——注册表缓存安全。

全部改动在**主环境 `.venv`**。dm_bridge 子进程仅承担大漠 COM 调用；新认领路径
（进程表/互斥锁/文件 IO）是纯 Win32 API，不经桥接，不涉及输入注入与截图。

```
 主环境 .venv (Python 3.12)                dm_bridge (Python 3.8, 32bit)
 ┌──────────────────────────────┐          ┌─────────────────┐
 │ claim_registry (文件+mutex)   │          │ 大漠 COM          │
 │ claim 原语 (枚举/ppid/锁)     │  stdin→  │  find_windows    │
 │ 自举识别 (token/dropdown OCR) │ ←stdout  │  send_string 等  │
 └──────────────────────────────┘          └─────────────────┘
```

## Goals / Non-Goals

**Goals:**
- 认领成本从"秒级侵入式识别"降为"毫秒级只读查表"：KK 侧 `pid == kk_pid`，war3 侧
  `ppid(war3_pid) == kk_pid`
- 三套认领协议收敛为一个原语；全局串行锁退役
- 注册表承载跨实例共享：归属一次识别全局复用，重启免识别
- 单开零识别开销；认领失败语义统一为抛异常终止

**Non-Goals:**
- 不改输入注入链路与自举识别内部实现（token 发送、下拉框 OCR 复用现有代码，
  只是调用次数从 N×M 降为每实例一次）
- 不支持跨机协调（注册表是本机文件）
- 不处理两个无 `target_player` 实例并存的歧义场景（本就无身份可区分，保留现状语义）

## Decisions

### D1: 注册表 = JSON 文件 + NamedMutex，不用共享内存/网络

`%LOCALAPPDATA%\GameBot\claim_registry.json`，写用 tmp+`os.replace` 原子替换，
读-改-写全程持 `Local\GameBot_Registry` 命名互斥锁。

- 选文件而非共享内存：与已移除的 team_ipc 同构、人可读可排查、实例全灭后文件自然
  过期重建；共享内存代码量大且无调试收益。
- 机器级路径而非项目目录：多开两个 exe 可能装在不同目录，注册表必须跨安装目录共享。
- 读时剪枝，无心跳线程：实例条目以 `OpenProcess(pid)` 判活，省掉心跳写竞争。

### D2: 归属判定的两个基元

```
 war3:  ppid( get_window_process_id(hwnd) ) == self_kk_pid     # 直接父进程
 kk_*:       get_window_process_id(hwnd)  == self_kk_pid       # 同进程窗口
```

`ppid` 用 Toolhelp32 快照（tests/manual/test_kk_war3_relation.py 已有可搬实现）。
两者都满足"读图期零操作"约束，取代所有阶段敏感的识别路径。

### D3: 自举 = 场景分派的唯一识别路径，无回退

场景由任务入口语义决定（调用哪个 claim 接口）而非探测：

| 任务形态 | 首个调用 | 自举识别 |
|---|---|---|
| endless/game_count 等多局任务 | `claim_room_window` | 房间聊天 token |
| 需大厅操作的流程（建房/加房） | `claim_hall_window` | 下拉框 OCR |
| fishing/endless_single 等局内任务 | `claim_war3_window` | war3 聊天 token |

自举成功后写 `kk_owner[kk_pid] = player`（含进程启动时间戳）；游戏内 token 认领
顺手推出 `kk_pid = ppid(war3_pid)` 同样写表——每条识别路径都反哺注册表。
注册表已命中 `player → kk_pid`（重启/其他脚本已识别）时自举整体跳过。

hall 下拉框 OCR 按 kk_pid 串行化保留 `Local\GameBot_KK_Hall_Identify_PID_{pid}` 锁
（同 pid 并发识别互踩防御，成本极低）。

### D4: 统一认领原语 claim_window

```
claim_window(kind, matches_self, identify=None, timeout, retry_interval, stop_event):
    缓存 hwnd 存活且注册表复核一致 → 直接返回
    loop until timeout:
        for hwnd in enumerate_candidates(kind):
            hwnd 已失效/最小化 → skip
            mutex(f"Local\\GameBot_Claim_{kind}_{hwnd}").try_acquire 失败 → skip
            owner = resolve_owner(hwnd)          # 只读：pid/ppid → 注册表 → player
            owner 未知且 identify 提供 → owner = identify(hwnd)   # 仅自举场景传入
            owner == target → 持锁 + 写注册表 + 返回
            否则 → 释放锁，下一个
        wait(retry_interval, stop_event)
    raise ClaimError("...候选数/占用情况")
```

war3/kk_room/kk_hall 共用一个骨架；差异只剩候选枚举条件与 owner 解析规则。
原 `mismatched` 集合删除：确定性判定下不匹配是终态，无需黑名单。

### D5: 单开快速路径 — 跳识别不跳锁

census==1 且该类候选数==1 → 直接持锁认领 + 注册，不做识别。
候选数>1 退回完整协议（防止误取他人手动游戏的窗口）。

中途加入保护：快速路径仍持 per-hwnd 互斥锁，晚加入脚本枚举到该窗口拿不到锁即跳过；
重复 `target_player` 在注册阶段被拒（Registry 拒绝，新实例报错退出）。

### D6: 失败语义统一

认领超时 → 抛 `ClaimError`（新增异常类型），任务终止。原"返回 0 / 返回 (0,0) +
调用点 raise"的分叉写法删除；调用点不可能忘记检查。

### D7: 绑定上下文边界

认领协议本身全程只读，不进 `bind_window`。仅自举识别沿用既有绑定边界：

- 房间 token：`bind_window(kk 后台参数)` → 点击输入框 → send_string → Enter →
  解绑后 `force_refresh_layered(hwnd)` 再 WGC OCR（Layered 刷新定稿不变）
- 大厅下拉框：`bind_window` → 点头像 → 解绑 → 绑定新下拉框 → OCR → ESC
- war3 token：`set_client_size` → `bind_window(war3 后台参数)` → send_msg → OCR

这些实现原样搬迁，只是从"每窗口每轮"降为"每实例一次"。

## Risks / Trade-offs

- [注册表文件损坏/脏写] → 损坏按空表处理 + 告警；互斥锁守护使撕裂概率极低
- [PID 复用错认] → kk_owner 条目带进程启动时间戳（GetProcessTimes），读时复核
- [hwnd 复用错认] → windows 条目读时复核归属关系（war3 复核 ppid、kk 复核 pid），
  不一致即失效
- [游戏内重启且注册表冷启动] → 走 war3 token 自举（用户定稿，无回退），代价与现状相同
- [屏外大厅下拉框不可点] → 大厅自举仅用于"账号停在大厅"场景，此时大厅前台可见；
  游戏内场景不走大厅路径，该风险不触发
- [exe 入口实例锁 `GameBot_task_{key}` 与注册表重复玩家校验并存] → 保留两层：exe 锁
  防同配置双开（含无 player 配置），注册表防跨启动方式的同名玩家冲突

## Migration Plan

1. `driver/claim_registry.py`：注册表读写 + 活性剪枝 + NamedMutex 守护
2. `business/claim.py`：`claim_window` 原语 + `ClaimError`
3. KK 侧接线：`claim_room_window`/`claim_hall_window` 走原语，自举结果写注册表
4. war3 侧接线：`claim_war3_window` → ppid 判定；`find_game_window` 分派不变
5. 任务层去胶水：endless/game_count 删 `_identify_claim_window` 与重复 `_claim_kk_room`
6. 删除过时代码与配置段（清单见 proposal What Changes）
7. 测试重写 + AGENTS.md / docs 同步

回滚：变更集中于认领链路，git 回退 commit 即可；注册表文件为新增，删除无副作用。

## Open Questions

- 注册表文件是否需要手动"清空"入口（诊断脚本/参数）——实现期可加一个
  `tests/manual` 清理脚本，非阻塞项
- 无 `target_player` 的多脚本并存是否值得在注册表加告警——先记录 warning 观察
