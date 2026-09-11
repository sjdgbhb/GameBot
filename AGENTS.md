# GameBot 项目备忘

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
