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

### 截图（已迁移至 WGC，大漠不再承担）
- **现状**：项目截图统一走 WGC（Windows Graphics Capture，`runner/driver/wgc_capture.py`），
  按 hwnd 从 DWM 取帧，客户区坐标，不进游戏进程
- **大漠 Capture（gdi2/dx2）已废弃**：dx 截图与 dx 系鼠标注入共用游戏进程内钩子，
  并发截图会撕开注入锁卡一帧，是迁移 WGC 的根因
- **PIL ImageGrab / PrintWindow 已移除**：项目只维护 WGC 一种截图方式，不保留降级路径

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
- 流程：WGC 取帧 → ndarray → RapidOCR 识别（`ocr_lines_from_array` / `ocr_from_array`）
- 大漠 OCR 代码已移除，不保留接口

## 绑定模式

大漠通过 `BindWindowEx` 绑定窗口。绑定模式只有两种：

| 模式 | 说明 | 配置段 | 适用场景 |
|------|------|--------|----------|
| **前台**（foreground） | `normal` + `normal` + `normal`，简单可靠，但会抢占前台 | `[xx.bind_foreground]` | 单开、调试 |
| **后台**（background） | 不抢占前台，支持多窗口；定稿参数见下 | `[xx.bind_background]` | 多开、需要后台操作 |

后台绑定定稿参数（dm 3.1233 免费版实测）：

- `display=dx2`（仅作输入注入配套钩子，截图统一走 WGC）
- `keypad=windows`
- `mouse=dx.mouse.position.lock.api|dx.mouse.position.lock.message|dx.mouse.state.message|dx.mouse.input.lock.api`
  （`windows2` 即前三段简写）
- `public=dx.public.active.api`、`mode=4`

### 模式选择规则
- 由命名空间级 `bind_mode` 决定（`foreground` 或 `background`）
- 切换方式：任务/变体文件写 `[war3]`/`[kk]` 段的 `bind_mode` 覆盖 `war3.toml`/`kk.toml` 默认值（绝对寻址补丁）；任务 `[this]` 不支持 bind_mode
- 调用点用 `resolve_bind_cfg(ns_cfg)`（GameBot.config）按 `bind_mode` 实时选表，配置字典不生成 `bind` 派生字段

### 后台模式注意事项
- **需要管理员权限**
- 不可连续操作，需加延时（`bind_delay`）
- **war3 读图期禁操作窗口**：加载页只允许只读检测（WGC/OCR）与内核互斥锁，
  改尺寸/注入 dx 绑定会使并发读图的另一实例卡死加载页（详见
  [KK平台特性](kk-platform.md) 与 AGENTS.md）

## 重要约束

### 线程亲和
- 大漠 COM 对象是线程亲和的，只能在创建它的线程中使用
- 桥接子进程在主线程串行处理所有 COM 调用，天然满足此约束
- **不要在多线程中直接调用大漠 COM**

### 绑定状态易被破坏
大漠绑定丢失后 COM 不抛异常，`move_to`/`left_click` 等调用**不报错但实际落空**，
调用方若不检查返回值会误以为操作成功。

> 注：`force_refresh_layered` 旧实现取消/恢复 `WS_EX_LAYERED` 会破坏后台绑定，
> 已改为纯尺寸扰动刷新，不再有此约束（详见 [KK平台特性](kk-platform.md)）。

> 截图已迁移至 WGC，不再依赖大漠绑定状态，PrintWindow 降级路径已移除。

### dx2 截图限制（历史，截图已迁移 WGC）
- dx2 截图与 dx 系鼠标注入共用游戏进程内钩子，并发截图会撕开注入锁卡帧——这是迁移 WGC 的根因
- 窗口需要部分在屏幕外（Win7/Vista 不需要）
- 当前大漠 `display=dx2` 仅作为鼠标/键盘输入注入的配套钩子保留，不再用于截图

### COM 注册
- 首次使用或版本变更时需要注册 dm.dll
- 注册需要管理员权限
- 桥接子进程启动时会检查版本，不符时尝试静默重注册

## 截图方式对比

| 方式 | 坐标系 | 线程安全 | 状态 |
|------|--------|----------|------|
| **WGC**（`wgc_capture.py`） | 客户区 | 是 | ✅ 当前唯一截图方式，按 hwnd 从 DWM 取帧 |
| 大漠 Capture（gdi2/dx2） | 客户区 | 否（COM线程亲和） | ❌ 已废弃，与 dx 鼠标注入共用钩子会卡帧 |
| PIL ImageGrab | 屏幕 | 是 | ❌ 已移除，需坐标转换 |
| PrintWindow | 客户区 | 是 | ❌ 已移除，layered 窗口降级路径不再需要 |

### 迁移说明
项目截图已统一走 WGC，消除坐标转换与 layered 特判。大漠仅剩鼠标/键盘输入注入。
详见 [docs/change_logs/war3后台开发记录.md](../change_logs/war3后台开发记录.md)。

## 相关文档

- [驱动层](../modules/driver.md) —— 大漠能力的代码封装
- [KK平台特性](kk-platform.md) —— layered 窗口问题的背景
- [架构总览](../architecture/overview.md) —— 双环境隔离的设计理由
- [war3 后台开发记录](../change_logs/war3后台开发记录.md) —— WGC 迁移全过程
