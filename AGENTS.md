# GameBot 项目备忘

## 文本输入体系（2026-09-11 实机测试）

### SendString 兼容性结论（测试脚本 tests/manual/test_send_string_compat.py）

| 场景 | SendString | SendString2 | SendStringIme |
|---|---|---|---|
| KK 大厅搜索框（Qt） | 中文/ASCII 正常 | 中文乱码风险 | 未测 |
| KK 密码弹窗（Qt） | 正常 | 正常 | 未测 |
| War3 聊天框 | **仅 ASCII**，中文被丢弃 | 同左 | **返回 1 但无任何输入**（前/后台均无效） |

- 生产代码统一用 `send_string`（新版 SendString）；`send_string2` 仅保留在驱动层和诊断脚本
- war3 聊天命令全是 ASCII（-delh、-rw 等），`send_string` 够用；中文聊天无可用方案，SendStringIme 实测无效（dm 3.1233）
- `dx.public.input.ime` 是绑定参数（BindWindowEx 的 public 字段，`|` 分隔组合），与前台/后台无关；属大漠收费功能，未启用
- `send_msg`（war3 聊天流程：开框→清残留→SendString→发送）不经过系统输入法，无需切换 IME

### send_msg 聊天框残留字符防护

后台 windows 键盘通道消息投递有延迟，前一按键（如钓鱼收竿 s）可能在聊天框打开后才被游戏消化，误入聊天框变成 `s-delh`。
`send_msg` 已内置防护：开框前等待 `interface_switch_time`，开框后先按 5 次退格清残留。

### War3 后台鼠标模式实测矩阵（display=dx2, keypad=windows, mode=4）

| mouse | 结果 |
|---|---|
| `windows` | ❌ 受物理鼠标影响：物理指针在不可点击处时技能点不出；指针在窗口边缘触发视角平移 |
| `windows2` | ✅ 完全解耦：游戏光标与物理鼠标互不影响 |
| `windows3` | ❌ 同 windows |
| `dx.mouse.position.lock.api` | ⚠️ 点击可用，但游戏光标跟随物理鼠标 → 物理移动会干扰点击落点 |
| `dx.mouse.focus.input.api` / `clip.lock.api` / `state.api` / `dx.mouse.api` / `dx.mouse.cursor` | ❌ 同 windows |
| `windows2` + `dx.keypad.input.lock.api` / `dx.keypad.api` | ✅ 同 windows2（keypad 换法不影响） |

- 结论：**war3 后台鼠标用 `windows2|dx.mouse.input.lock.api`**
  （即 position.lock.api|position.lock.message|state.message|input.lock.api）
- `dx.mouse.position.lock.api|dx.mouse.raw.input` 组合在 dm 3.1233 上 BindWindowEx 直接失败（ret=0），不可用
- 收费项：`dx.mouse.raw.input`、`dx.mouse.input.lock.api2/api3`、`dx.mouse.cursor`，
  免费版 BindWindowEx 传入即失败。api2/api3 的文档描述"后台操作时前台鼠标会移动"
  正是 war3 前台干扰场景 —— 免费版用 input.lock.api 覆盖
- `dx.mouse.input.lock.api`（未标收费）"封锁系统API锁定鼠标输入接口"，
  **2026-09-12 实测有效**：windows2 追加该参数后，war3 前台晃动物理鼠标
  游戏光标也不跟随（此前 war3 前台时 raw input 直读物理鼠标，windows2 管不住，
  症状：光标一卡一卡、跟随系统鼠标、注入点击落在物理光标处→按 A 停在"选择目标"）
- **并发 dx2 Capture 会撕开鼠标注入锁**（2026-09-12 双向解耦矩阵实测确认）：
  TextMonitor/start_text_watcher 每 `monitor_interval`(0.2s) 一次 `dm.Capture`，
  与 dx 系鼠标注入共用游戏进程内钩子——截图在飞期间注入锁失效，目标选择态
  点击（A/M+左键）落到物理光标处或被丢弃，游戏光标跟随物理鼠标、画面周期性卡顿。
  接取阶段"正常"是假象：点击发生在监测线程启动前/截图间隙。
  - 点击矩阵（`--no-watch`，全部带 `public=dx.public.active.api`）：
    ①脚本→系统 全组合 OK（注入从不带动系统光标）；
    `windows2|input.lock.api` 及含它的超集 ②③ 全过；
    `windows2` 缺 input.lock.api → ②OK ③FAIL（选择态点击路由需要 input.lock.api）；
    `position.lock.api` 单用 → ②FAIL ③OK（点击能落但光标跟随）；
    `windows`/`windows3`/`lock.message`/`input.lock.api` 单用 → 全挂
  - 曾试 `dm.input_guard()`（`_io_lock` 包住关键输入序列防并发截图），已回退：
    截图在持锁区段之外仍会周期性卡顿/丢光标，不满足"截图不能影响脚本流程"
  - 根因是 dx 系 Capture 固有的卡帧/撕锁（bridge 已串行 COM 调用，并发不是根源），
    任何走大漠 dx 截图的方案（含同步轮询）都无法满足"截图不影响主流程"
  - 待实施方案（WGC）：截图改走 Windows Graphics Capture（`windows-capture`，仅主环境，
    按 hwnd 建会话），从 DWM 合成面取帧不进游戏进程；TextMonitor 架构不动。
    第一阶段替换 OCR 监测截图，第二阶段全项目截图统一为 WGC 并删除大漠 Capture /
    PrintWindow / ImageGrab 代码。**不做兜底/回退**：WGC 失败直接抛错终止任务，
    不退回大漠截图或前台模式 → 见 `docs/change_logs/war3后台开发记录.md`
  - `dx.public.active.api` 保留：dx 系绑定要求窗口处于激活态
  - 定稿：`mouse=windows2|dx.mouse.input.lock.api`、`public=dx.public.active.api`
  - 注意：KK 的"锁定鼠标在窗口内"必须关——它把真实光标钳进 war3 窗口，
    导致大漠注入改走真实光标且物理鼠标被钉死
  - 注意：多开机器上可能存在多个 `Warcraft III` 窗口（KK 残留闲置进程），
    `find_window`/`enum` 顺序不稳定，绑错窗口症状与注入失效完全相同（落另一个实例）
  - 探针 `--click [miniX,miniY,X,Y]` 做实机 A+点击验证（set_client_size 统一尺寸 +
    move_to_minimap_point 生产路径 + 默认并发截图压力，`--no-watch` 对照）
- 探针脚本：tests/manual/test_war3_bind_probe.py

**任务入口统一用 `war3.find_game_window()`**：后台模式用 `find_window`（不要求前台），
前台模式用 `get_active_window`。不要用 `dm.get_active_window` 找 war3 窗口 ——
它要求 war3 前台，后台模式下若 mouse 配置不含 input.lock.api 会踩 raw input 干扰的坑。

### 后台模式窗口尺寸设置

- `set_client_size` 必须在 `bind_window` **之前**调用：dx2 挂钩后 resize 会重建交换链导致闪屏数秒
- `set_client_size` 已对齐目标尺寸时提前返回，不触发无谓 resize
- `public=dx.public.active.api` **必须保留**：此前验证 "public='' 通过" 只测了绑定/截图，
  未测选择态点击；缺失时 A+左键失效（详见上方点击矩阵结论）

## 截图与 OCR 体系

### 当前状态

- **后台窗口截图**：大漠 Capture（gdi2/dx2），客户区坐标，无需转换
- **前台/屏幕截图**：PIL ImageGrab，屏幕坐标，需手动转换客户区→屏幕
- **OCR**：统一用 RapidOCR（ONNXRuntime 后端），不用大漠 OCR
- **找图找色**：大漠 FindPic/FindColor/GetColor
- **AI 推理**：ONNXRuntime（宝箱检测、战斗状态检测）

### Layered window 刷新（2026-09-01 更新）

KK 平台 Qt 5.15.2 窗口是 `WS_EX_LAYERED`，后台输入/点击后画面不刷新。
解决方案：`force_refresh_layered(hwnd)` — 取消 layered → RedrawWindow → 恢复 layered。
截图继续用大漠 Capture（gdi2/dx2），无需 PrintWindow。
已在 hall_manager/join_room/room_manager 的输入/点击操作后调用。

**重要约束（2026-09-01 实机测试确认）**：
- `force_refresh_layered` 会取消/恢复 `WS_EX_LAYERED`，**破坏大漠后台绑定状态**。
- **不能在 `bind_window` 上下文内调用**，否则后续 `move_to`/`left_click` 等操作会落空。
- 正确做法：拆成两段 bind，在中间调用 `force_refresh_layered`：
  ```python
  with dm.bind_window(hwnd, bind_cfg=bind_cfg):
      # 输入密码等操作
  dm.force_refresh_layered(hwnd)  # 在 bind 之外刷新
  with dm.bind_window(hwnd, bind_cfg=bind_cfg):
      # 点击确认等后续操作
  ```
- 已在 `create_room`（输入密码→刷新→点击创建）和 `join_room`（输入密码→刷新→点击确认）中应用此模式。

### 待办：统一截图方式，消除 ImageGrab 坐标转换

**目标**：把以下 ImageGrab 场景改为大漠截图（客户区坐标，无需转换）。

| 场景 | 文件 | 当前方式 | 改造难度 |
|---|---|---|---|
| 圣痕面板 OCR | `runner/tasks/war3/jiubing2/others/upgrade_stigmata.py:330` | ImageGrab + 手动坐标转换 | 低 — war3 窗口已绑定，改走 `base.ocr_lines` |
| 宝箱检测 | `runner/tasks/war3/jiubing2/others/patrol_loot.py:486` | ImageGrab 全屏截图 | 中 — 需在绑定上下文内调用，或用 `capture_to_temp` + `detect_chests` |
| 战斗状态检测 | `runner/tasks/war3/jiubing2/others/patrol_loot.py:239` | ImageGrab 独立线程连续截帧 | 高 — 大漠 COM 非线程安全，需重构线程模型 |

**注意事项**：
- `inference/local.py` 中的 `ocr_screen`/`ocr_lines`（ImageGrab 版）和 `capture_and_detect_chests`/`capture_and_predict_combat` 是 ImageGrab 入口
- `inference/local.py` 中的 `ocr_from_file`/`ocr_lines_from_file`/`detect_chests`/`predict_combat_batch` 是文件入口（可配合大漠截图使用）
- 战斗状态检测的线程模型重构是主要障碍，大漠 `bind_window` 不是线程安全的
- `inference/worker.py` 中有对应的子进程版本（ImageGrab），如统一截图方式也需同步处理
