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

## 开发前必读
- 了解架构 → [架构总览](docs/architecture/overview.md)
- 开发某模块 → [模块卡片](docs/modules/) 中找到对应模块，阅读其职责/依赖/禁忌
- 理解游戏背景 → [游戏机制](docs/domain/game-mechanics.md)
- 新增功能 → [开发指南](docs/guides/)

---

以下为实机测试踩坑记录与待办：

## 后台绑定与输入（war3）

**定稿**（dm 3.1233 免费版）：`display=dx2`、`keypad=windows`、
`mouse=windows2|dx.mouse.input.lock.api`、`public=dx.public.active.api`、`mode=4`

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

## KK 平台窗口（Layered 刷新）

- KK Qt 窗口是 `WS_EX_LAYERED`，后台输入/点击后须 `force_refresh_layered(hwnd)` 刷新
- **禁止在 `bind_window` 上下文内调用**（破坏绑定状态）；拆两段 bind，中间刷新：
  ```python
  with dm.bind_window(hwnd, bind_cfg=bind_cfg):
      # 输入密码等操作
  dm.force_refresh_layered(hwnd)  # 在 bind 之外刷新
  with dm.bind_window(hwnd, bind_cfg=bind_cfg):
      # 点击确认等后续操作
  ```
- 已应用：hall_manager/join_room/room_manager、create_room、join_room

## 文本输入（SendString）

- 生产代码统一 `send_string`；`send_string2` 仅留驱动层/诊断脚本
- war3 聊天仅 ASCII 可用；SendStringIme 实测无效，无中文聊天方案
- `send_msg` 已内置防残留：开框前等 `interface_switch_time`，开框后按 5 次退格

## 多开单任务（非组队）用法（2026-09-15）

同一台机器两个玩家各自跑同一任务、互不干扰，用"变体配置"模式（参考 ingame_special/fishing 变体）：

- 变体文件：`tasks/<组>/<任务>_<玩家名>.toml`，`extends` 基础任务，`[this]` 只写
  `target_player`（非空自动推导 bind_mode=background）；可加 `[float_window] y`
  错开浮窗、`[hero.xxx]` 覆盖账号差异配置（hero 浅合并，子键整表覆盖须写全字段）
- 启动：`.venv\Scripts\python -m GameBot.runner.tasks.war3.jiubing2.<组>.<任务> <任务>_<玩家名>`
  （如 `...endless.endless endless_善木木`）
- 隔离机制：
  - KK 侧 `claim_room_window`：向房间聊天输入框发随机 token（含本进程 pid 标记），
    OCR 聊天记录区"玩家名：token"提取归属；认领后拿 `owner_pid`，
    房间/弹窗/掉线处理全按 PID 过滤。坐标在 `kk.toml [this.multi_instance]`
  - war3 侧 `claim_war3_window(identify=identify_war3_owner)`：加载页面 OCR 玩家列表
    判归属（无需进游戏），命名互斥锁防抢占；多局任务局间须 `release_war3_claim`，
    旧 hwnd 销毁后复领新窗口
  - **认领失败直接终止任务**——归属未确认时继续运行可能误操作另一账号窗口
- 启动要求：账号停留在 **KK 房间**内（创建好密码房即可运行）
- 注意：浮窗停止键 NumPad- 是全局热键，两个脚本同时按会一起停；单独停用各浮窗 ✕ 按钮
