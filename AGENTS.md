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

- 结论：**war3 后台鼠标只能用 `windows2`**（= lock.api|lock.message|state.message 组合）
- `dx.mouse.position.lock.api|dx.mouse.raw.input` 组合在 dm 3.1233 上 BindWindowEx 直接失败（ret=0），不可用
- 探针脚本：tests/manual/test_war3_bind_probe.py

### 后台模式窗口尺寸设置

- `set_client_size` 必须在 `bind_window` **之前**调用：dx2 挂钩后 resize 会重建交换链导致闪屏数秒
- `set_client_size` 已对齐目标尺寸时提前返回，不触发无谓 resize
- `dx.public.active.api`：war3 矩阵验证以 public="" 通过；如绑定异常可考虑恢复

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
