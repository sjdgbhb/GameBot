# GameBot 项目规则与备忘

> 详细文档位于 [docs/](docs/README.md)。本文件保留 AI 每次会话必须遵守的核心规则，以及实机测试踩坑记录。

## 语言规则
- 始终使用简体中文回答
- 代码注释使用中文
- 文档和说明使用中文
- 技术术语可保留英文，但需提供中文解释
- 变量名、函数名等代码标识符使用英文

## 项目概述
GameBot — 魔兽争霸3 RPG地图"九种兵器2"的 Python 自动化脚本系统（含 Web 配置端）。
- 平台：仅 Windows（pywin32、COM 对象、Windows API）
- 包管理：uv（pyproject.toml，uv_build 后端）
- 核心依赖：大漠插件 (DmPlugin) — Windows COM 自动化库（仅 32 位 Python 3.8 可用）

## 双环境隔离（核心约束）
- **主环境 Python 3.12（.venv）**：Web 服务器、全部业务逻辑、OCR/AI 推理（进程内）、模型训练
- **大漠桥接环境 Python 3.8 32位（.venv-dm）**：仅 dm_bridge 子进程使用，大漠 COM 要求
- **禁止在 .venv-dm 安装** Web/OCR/AI 依赖（fastapi、onnxruntime、rapidocr 等）
- 跨环境调用：主环境通过 dm_bridge 子进程调用大漠 COM，推理在主进程内直接执行
- 详见 [架构总览](docs/architecture/overview.md) → 双环境隔离

## 编码规范
- 配置值不要硬编码在代码中，应从 TOML 配置文件读取
- 物品快捷键从英雄配置的 `inventory` 列表获取，不要硬编码
- 修改代码前先阅读相关配置文件和业务层代码
- 遵循现有 TOML 配置继承机制；任务代码取自身参数用 `get_task_view(cfg, task_name)`（旧 `cfg["task"]` 已废弃）
- 新增任务模块时在 `src/GameBot/config/data/war3/jiubing2/tasks/` 下创建对应 TOML 配置（可用 `python -m GameBot.config new <任务名>` 生成模板）
- 详见 [配置系统](docs/modules/config.md) → 配置调用规范

## 实机测试规则
- 涉及实机测试（游戏/KK 窗口操作、大漠绑定、点击输入等）前，必须先由用户确认实机环境已搭好
- 禁止未经用户允许自动跑实机测试

## 开发前必读
- 了解架构 → [架构总览](docs/architecture/overview.md)
- 开发某模块 → [模块卡片](docs/modules/) 中找到对应模块，阅读其职责/依赖/禁忌
- 理解游戏背景 → [游戏机制](docs/domain/game-mechanics.md)
- 新增功能 → [开发指南](docs/guides/)

---

以下为实机测试踩坑记录与待办：

## 后台绑定与输入（war3）

**定稿**（dm 3.1233 免费版）：`display=dx2`、`keypad=windows`、
`mouse=dx.mouse.position.lock.api|dx.mouse.position.lock.message|dx.mouse.state.message|dx.mouse.input.lock.api`
（`windows2` 即前三段简写）、`public=dx.public.active.api`、`mode=4`

- 任务入口统一 `war3.find_game_window()`；禁止业务代码直接调 `dm.get_active_window`/`dm.find_window` 找 war3 窗口
- `set_client_size` 必须先于 `bind_window` 调用
- 禁止大漠 dx 截图（并发 Capture 撕开鼠标注入锁）；截图统一走 WGC

## 截图与 OCR（WGC）

- 截图统一 WGC（`runner/driver/wgc_capture.py`，`windows-capture==2.0.1`，仅主环境）；
  大漠仅剩输入注入；
- 找图找色 `visual.py`（WGC 帧 numpy 模板匹配，颜色串按大漠 RRGGBB 解析）；
  OCR RapidOCR 吃 WGC 帧 ndarray；AI 推理 ONNXRuntime
- 会话：`acquire()/release()` 引用计数（监测线程）、`for_hwnd(hwnd)` 常驻（一次性调用）；
  监测线程出错记 monitor.error/event.error，watch/wait_for/stop 时抛出
- 帧停滞分两级：窗口销毁/最小化/锁屏（OpenInputDesktop 不可达）抛 CaptureError；
  窗口健康但应用忙（war3 加载地图单线程不产帧）沿用最后一帧继续轮询，不误杀任务

## KK 平台窗口（Layered 刷新）

- KK Qt 窗口是 `WS_EX_LAYERED`，后台输入/点击后须 `force_refresh_layered(hwnd)` 刷新
- 刷新机制：1px 尺寸扰动（WM_SIZE 强制 Qt 重绘重推，全程保持 layered 无黑边）；
  非 layered 窗口走 RedrawWindow。纯扰动不破坏大漠绑定状态
- 已应用：hall_manager/join_room/room_manager、create_room、join_room
- 业务层无 `dm.sleep`：DmClientBase 未暴露大漠 Sleep，延时统一 `time.sleep`

## KK ↔ war3 进程/窗口关系（2026-10-02 实机，tests/manual/test_kk_war3_relation.py）

- **war3.exe 是开房 KK 客户端（Platform.exe）的直接子进程**，无中转；多开时各账号
  Platform.exe 由主实例派生（主实例 <- 客户端 <- war3），故归属判定必须用
  **直接父进程** `ppid(war3_pid) == 房间 owner_pid`，不能用祖先链包含匹配
- 窗口层无任何隶属：war3 与 KK 窗口的 parent/owner/rootowner 互不相指，线程独立
- 开局后该 KK 客户端的大厅+房间窗口被搬到 `(-32000,-32000)` 屏外
  （IsWindowVisible 仍为 true，可枚举可绑定）；**游戏期间该房间 UI 置灰不可操作**

## 文本输入（SendString）

- 生产代码统一 `send_string`；`send_string2` 仅留驱动层/诊断脚本
- war3 聊天仅 ASCII 可用；SendStringIme 实测无效，无中文聊天方案
- `send_msg` 已内置防残留：开框前等 `interface_switch_time`，开框后按 5 次退格

## 多开单任务（非组队）用法（2026-09-15）

同一台机器两个玩家各自跑同一任务、互不干扰，用"变体配置"模式
（支持变体的任务：endless/endless_single/fishing/patrol_loot/upgrade_stigmata/ingame_special）：

- 变体文件：`tasks/<组>/<任务>_<玩家名>.toml`，`extends` 基础任务，`[this]` 只写
  `target_player`，并用 `[war3]`/`[kk]` 段写 `bind_mode="background"` 覆盖命名空间默认
  （多开必须后台绑定；任务 `[this]` 不支持 bind_mode）；可加 `[base.float_window] y`
  错开浮窗、`[hero.xxx]` 覆盖账号差异配置（hero 浅合并，子键整表覆盖须写全字段）
- 启动：`uv run python -m GameBot.runner.tasks.war3.jiubing2.<组>.<任务> <任务>_<玩家名>`
  （如 `...endless.endless endless_善木木`）
- 隔离机制（注册表 + PPID 模型，`runner/driver/claim_registry.py` +
  `runner/business/claim.py::claim_window`）：
  - 机器级共享注册表 `%LOCALAPPDATA%\GameBot\claim_registry.json`
    （`Local\GameBot_Registry` 互斥锁守护）：`instances` 存活实例注册
    （重复 target_player 拒绝启动）、`kk_owner` kk_pid→player 映射
    （进程启动时间戳防 PID 复用）、`windows` 已认领窗口 `kind:hwnd→kk_pid`
    （IsWindow + 归属复核防 hwnd 复用）；配置项 `base.toml [this.claim_registry]`
  - 统一认领原语 `claim_window`：缓存复用 → 枚举候选 → IsWindow/最小化过滤 →
    per-hwnd 互斥锁 `Local\GameBot_{Kind}_{hwnd}` → 归属判定（只读）→
    未知时场景化自举 → 匹配持锁登记；超时抛 `ClaimError` 任务终止；
    单实例+单候选走快速路径跳过识别（仍持锁）
  - KK 侧归属 = `窗口 PID == kk_pid`：注册表命中直接判定；kk_pid 未知时
    自举——房间启动发聊天 token（坐标 `kk.toml [this.multi_instance]`，
    仅自举用）、大厅启动走头像下拉框 OCR（保留
    `Local\GameBot_KK_Hall_Identify_PID_{pid}` 串行锁）
  - war3 侧归属 = `ppid(war3_pid) == kk_pid`（Toolhelp32 直接父进程比对，
    纯只读零窗口操作，读图期/任意游戏阶段均可认领）；kk_pid 未知
    （游戏内启动且注册表未命中）时发聊天 token 自举（坐标
    `war3.toml [this.multi_instance]`，仅自举用），命中后由 ppid 推出
    kk_pid 写注册表
  - 弹窗/掉线等 PID 过滤路径读注册表 `kk_pid`，任务层不再传 `owner_pid`
  - 多局任务局间须 `release_war3_claim`，旧 hwnd 销毁后复领新窗口
  - **认领失败抛 ClaimError 直接终止任务**——归属未确认时继续运行可能
    误操作另一账号窗口；绝不可对未认领窗口发退出键清场

**读图期禁操作 war3 窗口（2026-09-18 实机定位）**：两个实例读图重叠时，
脚本在读图期对窗口做 `set_client_size`/`BindWindowEx`(dx2+active.api) 会导致
其中一方卡死加载页——WGC 帧流正常（加载页动画在跑）但读条永不推进，
`wait_enter_game` 120s 超时。手动双开同刻读图无此问题 → 肇事者是注入操作
而非读图并发本身。新认领协议归属判定为纯只读（进程关系比对 + 互斥锁），
读图期天然零窗口操作；进游戏后仍按"等待 → 统一尺寸 → 绑定"顺序操作。
- 启动要求：账号停留在 **KK 房间**内（创建好密码房即可运行）
- 注意：浮窗停止键 NumPad- 是全局热键，两个脚本同时按会一起停；单独停用各浮窗 ✕ 按钮

## EXE 打包（exe/build_all.py）

- 任务定义在 `exe/build_all.py` 的 TASKS；各任务 spec/入口/用户配置在 `exe/<task>/`
- spec 直接打包完整 `config/data/`（变体 TOML 运行时按名加载）；组装时再覆盖一遍保证最新
- **坑（2026-09-22）**：PyInstaller 从 Python 安装目录打包 VC 运行库，版本过旧
  （14.28）会让 onnxruntime_pybind11_state 初始化失败（"DLL 初始化例程失败"）；
  `build_all.py` 的 `_fix_vc_runtime` 在组装/更新时用 System32 较新版覆盖 `_internal/`
- `windows_capture`（WGC）是惰性导入的 Rust pyd，spec 里须 `collect_all` 收集
- exe 入口无旧全局配置：用户覆盖与 exe 路径补丁写进任务闭包 + 常用自加载闭包缓存
  （base/kk/war3.jiubing2）；多开用用户配置 `[tasks.<组>.<任务>] target_player = "玩家名"`，
  入口 `_remap_user_cfg` 的 NS 顶层键必须合并而非整表赋值（否则 `[war3]` 段会吞掉
  排在它前面的 `[tasks.*]` 段）
- 物品名写法 `item = "名称"`：inventory 与 `type="item"` 动作统一在 load_task 时解析为
  `item_id`（`resolve_item_names` / `resolve_action_item_names`）；exe 入口用户覆盖后须
  再补一次解析；业务侧只读 `item_id`，无 id 兼容兜底

## OpenSpec（规格驱动开发）

本项目已集成 [OpenSpec](https://openspec.dev/)（v1.13.1，`--tools devin`），用于单次变更的规划与规格管理。与 AGENTS.md 互补：AGENTS.md 是常驻规则，OpenSpec 是按需工作流（跑 `/opsx-*` 命令时介入）。

- 规格与变更产物在 `openspec/`（`specs/` 为既有真相，`changes/` 为进行中的变更，`changes/archive/` 为已归档）
- 工作流技能在 `.devin/skills/openspec-*/`，命令在 `.devin/workflows/opsx-*.md`
- 项目上下文已预填进 `openspec/config.yaml`（含双环境隔离、配置规范、绑定/Layered 约束等），生成 spec 时自动注入
- 当前为 core profile（6 个工作流）：`/openspec-propose`、`/openspec-explore`、`/openspec-apply-change`、`/openspec-update-change`、`/openspec-sync-specs`、`/openspec-archive-change`
- 扩展命令（new/continue/ff/verify/bulk-archive/onboard）用 `openspec config profile` 切换
- 更新 OpenSpec：`openspec update`（刷新技能/命令文件）
- OpenSpec 生成的 spec/tasks 仍须遵守本文件所有规则

## GitHub 认证（gh CLI）

- GitHub PAT 已配置在 `.devin/config.local.json` 的
  `mcpServers.github.headers.Authorization`（gitignored，勿打印/提交 token 内容）
- `gh` 命令前注入 `GH_TOKEN` 即可认证，**不要要求用户手动 `gh auth login`**：

```powershell
$c = Get-Content '.\.devin\config.local.json' -Raw | ConvertFrom-Json
$env:GH_TOKEN = (($c.mcpServers.github.headers.Authorization) -replace '^(Bearer|token)\s+', '')
gh <命令...>
```

- exec 每次是新 shell，env 不跨命令保留，须在同一条命令内注入
- dev/main 分支受保护：合入必须走 PR（`gh pr create --base dev` + `gh pr merge`），
  直接 push 会被仓库规则拒绝
