# KK 平台窗口特性

> 本文档记录 KK 平台客户端的窗口技术特性，这些特性直接影响驱动层和业务层的实现。

## KK 平台概述

KK 平台是魔兽争霸3的对战平台客户端，基于 Qt 5.15.2 开发。
玩家通过 KK 平台启动游戏、创建/加入房间、管理好友列表等。

## 窗口技术栈

- **框架**：Qt 5.15.2
- **窗口样式**：`WS_EX_LAYERED`（分层窗口）
- **渲染**：Qt 自己的渲染引擎

## Layered 窗口问题（核心）

### 问题
KK 平台窗口是 `WS_EX_LAYERED`（分层窗口）。当通过大漠后台输入/点击操作这些窗口后，
**画面不会自动刷新**——操作已经生效（比如密码已输入），但屏幕上看不到变化。

### 原因
Layered 窗口的绘制由系统合成管理，后台输入修改了窗口内容，
但 Qt 的渲染队列没有触发重绘，导致画面停留在操作前的状态。

### 解决方案
`force_refresh_layered`：1px 尺寸扰动（SetWindowPos w-1→w 触发 WM_SIZE，强制 Qt
全量重绘并重推 UpdateLayeredWindow 帧），全程保持 layered 无黑边；
非 layered 窗口走 RedrawWindow。

### 说明
- 纯尺寸扰动不破坏大漠后台绑定状态（旧实现取消/恢复 `WS_EX_LAYERED` 会破坏绑定，
  需拆两段 bind 在中间刷新；该兜底路径已删除）
- 已在创建房间（输入密码→刷新→点击创建）和加入房间（输入密码→刷新→点击确认）中应用

## 弹窗问题

KK 平台大厅经常弹出各种窗口（广告、活动、公告等），这些弹窗会干扰自动化操作。
业务层有专门的弹窗清理逻辑：按窗口类名、尺寸、OCR 关键词识别并关闭无关弹窗。

## 多开窗口认领

多开场景下，同一台电脑运行多个 KK 客户端实例。归属判定基于
**机器级共享注册表 + 进程关系**，不再依赖逐窗侵入式识别。

### 共享注册表（`runner/driver/claim_registry.py`）

- 文件：`%LOCALAPPDATA%\GameBot\claim_registry.json`；读写全程持
  `Local\GameBot_Registry` 命名互斥锁，写盘用临时文件 + `os.replace` 原子替换；
  损坏/缺失按空表处理告警自愈
- `instances`：存活脚本实例（注册时校验重复 `target_player`，读时剪枝死 PID）
- `kk_owner`：`kk_pid → {player, start_time}`，启动时间戳防 PID 复用错认
- `windows`：`kind:hwnd → kk_pid`；读时校验 `IsWindow` + 归属复核
  （war3 复核 `ppid(war3_pid)`，KK 窗口复核窗口 PID）

### 统一认领原语（`runner/business/claim.py::claim_window`）

缓存复用 → 枚举候选 → `IsWindow`/最小化过滤 → per-hwnd 互斥锁
（`Local\GameBot_{Kind}_{hwnd}`）→ 归属判定（只读 PID/PPID 查表）→
未知时场景化自举 → 匹配持锁登记注册表；超时抛 `ClaimError` 终止任务。
单开快速路径（注册表单实例 + 单候选）跳过归属识别，仍持锁登记。

### 归属判定

- KK 大厅/房间窗口：`窗口 PID == 本账号 kk_pid`；kk_pid 未知时按注册表
  `kk_owner` 反查该窗口 PID 的归属玩家
- war3 窗口：`ppid(war3_pid) == 本账号 kk_pid`（Toolhelp32 直接父进程比对，
  纯只读，读图期零操作，任意游戏阶段可用）

### 自举（仅 kk_pid 未知时一次性触发）

- 房间启动（endless/game_count）：房间聊天 token（前缀+PID hex+随机尾）→
  OCR 聊天记录区"玩家名：token"提取归属，写 `kk_owner` 反哺注册表
- 大厅启动（create_room/join_room）：头像下拉框 OCR 玩家名
  （保留 `Local\GameBot_KK_Hall_Identify_PID_{pid}` 串行锁防同 PID 互踩）
- 游戏内启动（fishing/patrol_loot 等局内任务）：war3 聊天 token 自举，
  命中后由 `ppid(war3_pid)` 推出 kk_pid 写注册表

### 约束

- 认领成功后持有窗口互斥锁至显式释放或进程退出（崩溃自动释放）
- 归属未确认时禁止对候选窗口做任何操作；认领超时抛 `ClaimError` 任务终止

## War3 窗口绑定模式

### 单开（前台绑定）
- `normal` 模式：前台鼠标/键盘真实输入
- 简单可靠，但操作时会抢占前台

### 多开（后台绑定，定稿参数）
- `display=dx2`、`keypad=windows`
- `mouse=dx.mouse.position.lock.api|dx.mouse.position.lock.message|dx.mouse.state.message|dx.mouse.input.lock.api`
- `public=dx.public.active.api`、`mode=4`
- **截图不走大漠**：统一 WGC（Windows Graphics Capture）常驻会话取帧
- **需要管理员权限**
- **读图期禁操作窗口**：两个实例读图重叠时对窗口改尺寸/注入 dx 绑定会使
  其中一方卡死加载页——加载页只允许只读检测（WGC/OCR）与内核互斥锁，
  进游戏后再统一尺寸并绑定

## 窗口尺寸要求

- War3 窗口客户区尺寸：1902x1033（所有坐标基于此尺寸标定）
- 对应 KK 平台设置：war3（非重置版），窗口模式，分辨率和窗口尺寸均设为 1920x1080
- 启用视距调整，视距高度 3000
- 运行时强制对齐窗口尺寸，不匹配会报错

## 相关文档

- [驱动层](../modules/driver.md) —— layered 刷新和窗口绑定的代码实现
- [大漠插件能力](dm-plugin.md) —— 后台绑定模式的详细说明
- [AGENTS.md](../../AGENTS.md) —— layered 刷新的实机测试记录
