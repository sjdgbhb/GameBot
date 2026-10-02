# Tasks

## 1. 共享注册表（claim-registry）

- [x] 1.1 新增 `runner/driver/claim_registry.py`：JSON 注册表（`%LOCALAPPDATA%\GameBot\claim_registry.json`）+ `NamedMutex("Local\\GameBot_Registry")` 守护 + tmp/replace 原子写；损坏按空表告警。验证：单元测试覆盖并发写、损坏自愈、空文件初始化
- [x] 1.2 实现实例注册：`register_instance(player, task)` 懒注册（首次认领调用时）；读时以 `OpenProcess(pid)` 剪枝死实例；重复非空 `target_player` 且原实例存活 → 抛错拒绝。验证：单测模拟两进程注册，同名玩家第二个被拒、死 pid 不阻挡
- [x] 1.3 实现 `kk_owner` 映射读写：写入带进程启动时间戳（GetProcessTimes），读取校验"存活 + 启动时间一致"。验证：单测覆盖写入/命中/pid 复用失效
- [x] 1.4 实现 `windows` 归属记录：`kind:hwnd → kk_pid`，读时校验 IsWindow + 归属复核（war3 复核 ppid、kk 复核 pid）。验证：单测覆盖 hwnd 失效与复核不一致条目被跳过

## 2. 统一认领原语

- [x] 2.1 新增 `utils` 内 `ClaimError` 异常类型。验证：`from GameBot.utils import ClaimError` 可用
- [x] 2.2 新增 `runner/business/claim.py`：`claim_window(kind, candidates_fn, mutex_prefix, resolve_owner, identify, timeout, retry_interval, stop_event)` 骨架——缓存复用（hwnd 存活+复核一致）→ 枚举 → IsWindow/最小化过滤 → per-hwnd mutex → owner 判定 → 匹配持锁登记/不匹配释放 → 超时抛 `ClaimError`。验证：单测模拟两窗口竞争认领、超时抛错、复用短路
- [x] 2.3 原语内实现单开快速路径：注册表存活实例数==1 且候选数==1 时跳过 owner 判定直接持锁登记。验证：单测模拟单实例场景无 identify 调用；候选数>1 时仍走完整判定

## 3. KK 侧接线（business/kk）

- [x] 3.1 `multi_instance.py` 重写 `claim_room_window`：走 `claim_window`，owner 解析 = `get_window_process_id(hwnd) == self_kk_pid`（注册表查 player→kk_pid）；kk_pid 未知时经 identify 回调做房间 token 自举并写 `kk_owner`。验证：单测 mock dm/注册表覆盖命中/未命中/超时终止
- [x] 3.2 `hall_manager.py` `claim_hall_window` 走原语：kk_pid 未知时下拉框 OCR 自举（保留 `Local\GameBot_KK_Hall_Identify_PID_{pid}` 串行锁），识别成功写 `kk_owner`；已知 kk_pid 直接按 pid 认领。删除 `hall_owner_cache` 接口与本地缓存字典。验证：单测对齐 test_hall_manager.py 重写后的用例
- [x] 3.3 `_find_hall_hwnd`/`dismiss_*_popups`/`join_room` 等 PID 过滤路径改读注册表缓存的 kk_pid（不再依赖任务层传 owner_pid）。验证：`find_windows(owner_pid=kk_pid)` 过滤行为不变

## 4. war3 侧接线（business/war3）

- [x] 4.1 `window_manager.py` 重写 `claim_war3_window`：走 `claim_window`，owner 解析 = `ppid(get_window_process_id(hwnd)) == self_kk_pid`（ppid 用 Toolhelp32 快照，直接父进程比对）；kk_pid 未知时经 identify 回调做 war3 聊天 token 自举，成功后 `ppid` 推出 kk_pid 写注册表。删除 `identify=` 回调参数与全局 `GameBot_War3_Claim` 锁。验证：单测模拟父子进程表覆盖匹配/不匹配/超时抛 ClaimError
- [x] 4.2 保留 `find_game_window` 前台/后台分派语义不变；后台路径内部走新原语。验证：现有调用点（`find_game_window` 全部调用方）行为不变
- [x] 4.3 `release_war3_claim` 保留释放语义：释放互斥锁并清缓存句柄/注册表窗口记录。验证：单测覆盖局间释放后复领

## 5. 任务层去胶水

- [x] 5.1 endless.py / game_count.py 删除 `_identify_claim_window` 分阶段回调，do_war3 认领直接调 `claim_war3_window`（无 identify 参数）；删除 `_quit_stuck_war3_windows` 对未认领窗口的清场路径中违反"未认领不触碰"语义的部分。验证：任务代码不再引用已删除 API，`ruff check` 通过
- [x] 5.2 重复的 `_claim_kk_room` 下沉为 `KKBusiness` 公共方法（认领失败抛 ClaimError 语义内建）。验证：两个任务文件调用点改为公共方法，行为不变
- [x] 5.3 其余任务（fishing/endless_single/patrol_loot/upgrade_stigmata/ingame_special/wind_dragon 系）确认 `find_game_window` 局内自举路径生效，逐任务核对 target_player 注入点无遗漏。验证：全局搜索无对已删除接口的引用

## 6. 配置与过时代码清理

- [x] 6.1 `war3.toml` 删除 `[this.multi_instance.loading_page]` 段；`kk.toml`/`war3.toml` 的 chat token 坐标与超时配置保留并补注释标注"仅自举使用"。验证：`test_war3_multi_instance_config_loads` 等配置结构测试更新通过
- [x] 6.2 新增注册表路径/超时配置项（放 `base.toml` 或各自 `[this.multi_instance]`，按配置规范定）。验证：配置加载测试通过
- [x] 6.3 删除 `identify_war3_owner`/`find_target_war3_hwnd`/`bind_war3_window`/`check_parent_child_relation`/`hall_owner_cache` 参数链及 `mismatched` 相关代码。验证：全局搜索零引用，`ruff check` 通过
- [x] 6.4 删除 `tests/manual` 中验证已删除机制的脚本（保留 `test_kk_war3_relation.py` 作关系验证工具）。验证：手动测试目录清单确认

## 7. 测试与文档

- [x] 7.1 重写 `tests/unit/test_multi_instance.py`、`test_hall_manager.py`、`test_endless_task_boss_timeout.py` 中失效用例，新增注册表与 claim 原语用例。验证：`uv run pytest tests/unit -x` 全绿
- [x] 7.2 集成/结构测试更新（`test_config_structure.py` 的 multi_instance 断言）。验证：`uv run pytest tests/integration -x` 全绿
- [ ] 7.3 实机验证：双开 endless，两账号同时读图互不干扰、各自认领正确窗口（需 KK 房间 + 需游戏窗口）。验证：双开跑一局无尽全程日志无错认/超时
- [ ] 7.4 实机验证：游戏内重启脚本——注册表命中免识别直接认领（需游戏窗口）。验证：重启后日志显示注册表命中、无 token 发送
- [x] 7.5 更新 `AGENTS.md` 多开用法段（认领机制描述改为注册表 + PPID 模型，删除"加载页只读认领"约束描述）与 `docs/` 对应模块卡片。验证：文档与新行为一致，无已删 API 引用
