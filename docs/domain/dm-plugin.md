# 大漠插件能力

> 本文档说明大漠插件的能力范围和约束，帮助理解驱动层的设计。

## 大漠插件概述

大漠插件（DmPlugin）是 Windows 平台的 COM 自动化库，提供窗口操作、截图、
找图找色、键鼠模拟等能力。广泛用于游戏自动化场景。
（OCR 不用大漠，项目统一用 RapidOCR，详见下文 OCR 章节。）

- **版本**：3.1233
- **DLL**：`external/dm/dm.dll`（不纳入版本控制）
- **COM 要求**：只有 32 位 Python 可创建 COM 对象（这是双环境隔离的根本原因）
- **注册**：需要管理员权限注册 DLL（首次使用或版本变更时）

## 能力清单

### 窗口操作
- 窗口绑定/解绑（`BindWindowEx`，支持前台/后台模式）
- 窗口查找/枚举（按类名/标题/PID 过滤）
- 获取窗口矩形、客户区矩形、前台窗口
- 窗口状态查询（可见/最小化/进程ID）

### 截图
- **后台截图**：`Capture`（gdi2/dx2 模式），客户区坐标，无需转换
  - gdi2：GDI 后台截图，兼容性好
  - dx2：DirectX 后台截图，适用于 DirectX 渲染窗口（如 War3）
- **前台/屏幕截图**：PIL ImageGrab，屏幕坐标，需手动转换客户区→屏幕
- **Layered 窗口降级**：PrintWindow + PW_RENDERFULLCONTENT（临时解绑大漠后截图）

### 找图找色
- `FindPic` / `FindPicEx`：按图片模板在指定区域找图
- `FindColor`：在指定区域找色
- `GetColor`：获取指定点颜色
- 图片模板为 BMP 格式，存放在 `resources/images/`

### 键鼠输入
- 键盘：按键、按下/弹起、发送字符串
- 鼠标：移动、左/右键点击、双击
- 支持前台和后台模式（后台模式不抢占前台）

### OCR
- 项目统一用 RapidOCR（ONNXRuntime 后端），不用大漠自带 OCR
- 流程：大漠截图存文件 → RapidOCR 识别文件（`ocr_lines_from_file` / `ocr_from_file`）
- 大漠 OCR 代码已移除，不保留接口

## 绑定模式

大漠通过 `BindWindowEx` 绑定窗口。绑定模式只有两种：

| 模式 | 说明 | 配置段 | 适用场景 |
|------|------|--------|----------|
| **前台**（foreground） | `normal` + `normal` + `normal`，简单可靠，但会抢占前台 | `[xx.bind_foreground]` | 单开、调试 |
| **后台**（background） | `gdi2`/`dx2` + `windows3` + `windows`，不抢占前台，支持多窗口 | `[xx.bind_background]` | 多开、需要后台操作 |

### 模式选择规则
- **非组队 / 单成员组队**：由配置 `bind_mode` 决定（`foreground` 或 `background`）
- **多成员组队（成员数 > 1）**：强制 `background`，忽略 `bind_mode` 配置
- 配置优先级：顶层任务的 `[this].bind_mode` > `war3.bind_mode` / `kk.bind_mode`（命名空间级开关）
- 解析结果写入 `war3.bind` / `kk.bind`，业务代码始终读 `bind` 段即可

### 后台模式注意事项
- **需要管理员权限**
- dx2 要求窗口部分在屏幕外（Win7/Vista 不需要）
- 不可连续操作，需加延时（`bind_delay`）

## 重要约束

### 线程亲和
- 大漠 COM 对象是线程亲和的，只能在创建它的线程中使用
- 桥接子进程在主线程串行处理所有 COM 调用，天然满足此约束
- **不要在多线程中直接调用大漠 COM**

### 绑定状态易被破坏
大漠绑定后，以下操作会**悄悄破坏绑定状态**，导致后续 `move_to`/`left_click`/
`Capture` 等调用**不报错但实际落空**：
- `force_refresh_layered`：取消/恢复 `WS_EX_LAYERED` 样式会破坏后台绑定，
  不能在 `bind_window` 上下文内调用，需拆成两段 bind（详见 [AGENTS.md](../../AGENTS.md)）
- PrintWindow 降级截图：对 layered 窗口需临时 `UnBindWindow` 再 PrintWindow 再重绑，
  解绑/重绑出错则绑定丢失
- 绑定丢失后大漠 COM 不抛异常，调用方若不检查返回值会误以为操作成功

### dx2 截图限制
- dx2 会 hook GDI，导致 PrintWindow 黑屏
- 需要临时解绑才能用 PrintWindow 截图
- 窗口需要部分在屏幕外（Win7/Vista 不需要）

### COM 注册
- 首次使用或版本变更时需要注册 dm.dll
- 注册需要管理员权限
- 桥接子进程启动时会检查版本，不符时尝试静默重注册

## 截图方式对比

| 方式 | 坐标系 | 线程安全 | 适用场景 |
|------|--------|----------|----------|
| 大漠 Capture | 客户区 | 否（COM线程亲和） | 后台截图，已绑定窗口 |
| PIL ImageGrab | 屏幕 | 是 | 前台/全屏截图，独立线程 |
| PrintWindow | 客户区 | 是 | Layered 窗口降级截图 |

### 待统一事项
当前部分场景用 ImageGrab（需坐标转换），目标是统一为大漠截图（客户区坐标，无需转换）。
详见 [AGENTS.md](../../AGENTS.md) 的待办事项。

## 相关文档

- [驱动层](../modules/driver.md) —— 大漠能力的代码封装
- [KK平台特性](kk-platform.md) —— layered 窗口问题的背景
- [架构总览](../architecture/overview.md) —— 双环境隔离的设计理由
- [AGENTS.md](../../AGENTS.md) —— 截图方式统一的待办
