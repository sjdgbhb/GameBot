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

## 配置系统增量能力（2026-09-15）

- **provenance**：`load_task` 合并时记录每键来源链，`config.get_provenance(task)` 取用；
  CLI：`python -m GameBot.config order|explain|dump [--annotate]`（explain 查某键来源，
  dump --annotate 逐行标注来源，替代手写 merged_cfg 调试）
- **绝对寻址**：TOML 里写完整命名空间段（如 `[war3.jiubing2.tasks.others.fishing]`）
  = 直接给目标节点打补丁，合并阶段生效；编排任务调子任务参数用此写法，
  不再在业务代码里手动搬运（ingame_special 的 _apply_overrides 只剩 target_player 透传）。
  **禁止用完整路径写自身命名空间**（loader 拦截，提示改用 [this]）
- **有效任务视图 `cfg["task"]`**：`load_task` 把同组任务文件的 `[this]` 沿加载链深合并
  （如 endless_single → endless → endless_善木木），并**回写到叶子命名空间节点**——
  按路径读该任务段也拿到合并视图（兼容组队模式多任务闭包合并的场景）。
  任务代码取自身参数用 `cfg["task"]`。注意只含本组链——编排任务的子任务参数
  仍在各自命名空间节点（用绝对寻址打补丁）
- **派生逻辑共享**：`config/system/derive.py` 收敛派生推导——`resolve_item_names`
  （物品名→item_id）、`derive_bind_mode`/`select_bind_cfg`/`apply_bind_mode`（bind 选择）；
  组队等非 load_task 路径调 `apply_bind_mode(cfg, force_mode="background")`，
  不再手写派生拷贝（team/base.py 旧的两份重复实现已删）
- **命名空间根注册表**：`config/system/base.py` 的 `NAMESPACE_ROOTS`（base/kk/team/war3/web），
  不再扫描目录；新增任务/英雄/场景/变体文件无需登记（都在 war3 根内），
  仅新增一级命名空间（data/yy/）才加注册表一行；未登记的一级条目加载时告警。
  extends 分层约束（warn 阶段）：低层文件不得 extends tasks.*，task→task 放行
- **用户覆盖路由表**：`user.py` 的 `_USER_KEY_ROUTES` 声明式表——
  user_configs.json 键 → [(目标路径, 是否创建中间节点)]，"{task}" 占位任务命名空间；
  新增用户可调键只需加一行路由，不再写 setdefault 链
- **lint/new 脚手架**：`python -m GameBot.config lint`（结构校验：extends 声明/循环依赖/
  分层违例/未登记根条目为错误；变体约定、绝对寻址段存在性为警告）；
  `python -m GameBot.config new <tasks.*.名>` 生成模板（含 `_玩家名` 后缀自动探测基任务）
- 设计基准：`docs/review_reports/技术方案_配置系统重构.md`
