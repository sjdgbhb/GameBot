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
  - WGC 方案（第一阶段代码已完成，冒烟实测 2026-09-14）：截图走 Windows Graphics
    Capture（`windows-capture==2.0.1`，仅主环境，按 hwnd 建会话），从 DWM 合成面取帧
    不进游戏进程；`_ocr_region_text` → `WgcCapture.grab_client` → `ocr_from_array`。
    会话生命周期：`WgcCapture.acquire/release`（hwnd 引用计数），由
    TextMonitor.start/stop、start_text_watcher/stop_text_watcher 管理；
    监测线程出错记 monitor.error/event.error，watch/wait_for/stop 时抛出。
    **前置条件（实测）**：窗口被遮挡/移出屏幕无碍；最小化启动即报错；
    锁屏/RDP 断开期间帧流停止、解锁后自动恢复 → 挂机机禁止锁屏。
    第二阶段全项目截图统一为 WGC 并删除大漠 Capture / PrintWindow / ImageGrab 代码。
    **不做兜底/回退**：WGC 失败直接抛 CaptureError 终止任务，不退回大漠截图或前台模式
    → 见 `docs/change_logs/war3后台开发记录.md`
  - 钓鱼后台 2026-09-12 实测通过；WGC 第二阶段 find_color/find_pic 改走 WGC 帧后
    钓鱼 `_check_hook` 链路直接受影响，**须回归重测**（含 display 降 normal 的绑定复测）
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

### 当前状态（2026-09-14：全项目截图已统一 WGC，待实机回归）

- **截图**：统一 WGC（Windows Graphics Capture，`runner/driver/wgc_capture.py`），
  按 hwnd 从 DWM 合成面取帧，不进游戏进程；窗口被遮挡/移出屏幕均可取帧，
  **不可最小化、不可锁屏**（帧流停止 → `CaptureError`，无回退）
- **大漠仅剩输入注入**（`move_to`/`key_press`/`send_string` 等），不再承担任何截图职责；
  `display=dx2` 暂留待验证，确认 dx.mouse.* 不依赖 display 钩子后可改 `normal`
- **找图找色**：`visual.py` numpy 实现（WGC 帧 + `sliding_window_view` 模板匹配），
  颜色串按大漠 RRGGBB（RGB 序）解析；**调用接口与返回语义不变**
- **OCR**：RapidOCR（ONNXRuntime），输入为 WGC 帧 ndarray，不再落临时文件
- **AI 推理**：ONNXRuntime（宝箱 `detect_chests_from_array`、战斗 `predict_combat_from_arrays`）
- **ImageGrab / PrintWindow / 大漠 Capture 已全部移除**；WGC 失败直接抛 `CaptureError`
- 会话管理：`WgcCapture.acquire()`/`release()` 引用计数（监测线程用），
  `WgcCapture.for_hwnd(hwnd)` 常驻会话（业务一次性调用用，无需绑定上下文）

### Layered window 刷新（2026-09-01 更新）

KK 平台 Qt 5.15.2 窗口是 `WS_EX_LAYERED`，后台输入/点击后画面不刷新。
解决方案：`force_refresh_layered(hwnd)` — 取消 layered → RedrawWindow → 恢复 layered。
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
