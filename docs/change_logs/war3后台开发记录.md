# War3 后台开发记录

> 持续更新的后台模式（`bind_mode = "background"`）开发记录。每个条目记录：解决的问题、根因、方案、改动清单、验证方式。
> 绑定参数矩阵等实测结论同步维护在 [AGENTS.md](../../AGENTS.md)。

---

## 2026-09-12 后台实机测试：钓鱼通过，城门骚扰暴露 dx2 Capture 干扰

> 状态：**钓鱼已通过；城门骚扰问题单独立项（见下一条目），WGC 落地后钓鱼须回归** | 关联任务：`others/fishing`、`atomic/blackstone_gate_harassment`

### 测试范围与结论

| 任务 | bind_mode | 结果 |
|---|---|---|
| 钓鱼（`others/fishing`） | background | ✅ 全流程通过：抛竿、找色中钩检测、预判收竿、循环均正常 |
| 城门骚扰（`atomic/blackstone_gate_harassment`） | background | ❌ 选择态点击失效、光标干扰、周期性卡帧，详见下一条目 |

### 城门骚扰暴露的问题（摘要，详情见下一条目）

- 监测线程每 0.2s 一次 dx2 `Capture` 撕开鼠标注入锁：A+左键落空或落到物理光标处、游戏光标跟随物理鼠标、画面周期性卡帧
- 配套实测定稿鼠标组合 `windows2|dx.mouse.input.lock.api`、`public=dx.public.active.api`（矩阵过程见 AGENTS.md）
- 根因是 dx 系 Capture 固有的跨进程同步卡帧/撕锁，大漠截图体系内无解 → 决定迁移 WGC

### 后续行动

- WGC 迁移改动面较大（第一阶段换 OCR 监测截图，第二阶段全项目截图统一并删除大漠 Capture/PrintWindow/ImageGrab），改动清单见下一条目
- **钓鱼须在 WGC 落地后回归重测**：第二阶段 `find_color`/`find_pic` 将改为 WGC 帧上的 numpy 计算，钓鱼 `_check_hook` 找色链路直接受影响；且 `display` 可能从 dx2 降为 normal，绑定参数需复测
- 其他走大漠找图找色/截图的任务同步列入第二阶段回归范围

---

## 2026-09-12 OCR 监测截图改用 WGC，消除 dx2 Capture 对鼠标注入的干扰

> 状态：**第一阶段已实机验证通过**（2026-09-14：`--wgc-dump` 客户区偏移正确、WGC 压力下
> `--click` 三项解耦全过且无卡帧、城门骚扰后台端到端正常、4 场景帧流测试完成）
> | **第二阶段（全项目截图统一 WGC）代码已完成，待实机回归** | 关联任务：`atomic/blackstone_gate_harassment.toml`（城门骚扰，后台模式）

### 解决的问题

后台模式下 `TextMonitor` / `start_text_watcher` 监测线程每 `monitor_interval`(0.2s) 调一次大漠 `Capture`（display=dx2）。dx2 截图与 dx 系鼠标注入（`dx.mouse.position.lock.api|...|dx.mouse.input.lock.api`）共用游戏进程内的钩子，**每次 Capture 都会撕开注入锁并卡游戏一帧**，症状：

1. 选择态点击（A/M + 左键）落空或落到物理光标处 → 路线点、拾取、目标类技能失效
2. 游戏光标短暂跟随物理鼠标 → 光标在窗口边缘触发视角漂移，破坏坐标假设
3. 每次截图游戏卡顿一帧，卡顿时游戏光标短暂消失
4. 接取阶段"正常"是假象：点击发生在监测线程启动前或两次截图的间隙

实测（探针 `tests/manual/test_war3_bind_probe.py --click`）：无监测线程时 `windows2|dx.mouse.input.lock.api` 三项解耦全过；并发截图时仅该组合勉强保持点击有效，其余组合注入通道全被打回真实光标。

### 根因分析

- **不是并发 COM 调用的问题**：`bridge.py:_com_call` 已用 `self._lock` 串行所有 COM 调用；主线程一次大 `bind_window` 包住整个任务，监测线程的嵌套 bind 是幂等 no-op。
- **是 dx 系 Capture 的工作方式**：它要在游戏渲染线程的下一次 Present 里拷一帧出来，本身就是一次跨进程/跨线程同步，会卡住游戏一帧；dx 系鼠标锁是同一注入模块里的钩子，Capture 期间状态被打断。
- 佐证：曾试 `dm.input_guard()`（`_io_lock` 包住关键输入序列防并发截图）后回退——持锁区段之外的截图仍周期性卡顿/丢光标，说明卡顿是 Capture 固有的，和时序无关。
- 因此**任何走大漠 dx 系截图的方案都无法满足"截图不影响主流程"**：
  - 同步轮询（把截图挪到等待间隙，见下方"已否决方案"）只能避免截图插进点击序列，每次截图仍卡一帧。
  - 换 `dx3` / `dx.graphic.*` 只是换钩点，同步代价一样在；`gdi`/`gdi2` 对 D3D 渲染的 war3 是黑图；`normal` 是屏幕截图，后台被遮挡即失效。

### 方案：监测线程截图改走 Windows Graphics Capture（WGC）

WGC 从 DWM 合成面读取窗口自身的重定向表面，**完全不进游戏进程、不碰大漠钩子**；窗口被遮挡、在屏幕外都能拿到当前帧（不能最小化）。GPU 侧零拷贝出帧，只在需要像素时做一次 staging 回读，60fps 无压力。

`TextMonitor` 的原始设计意图就是"子线程既不碰大漠也不碰 win32gui，只把固定 bbox 转发给 OCR"（`text_monitor.py:177-179`），后来为支持后台多开改成 `_ocr_region_text → dm.capture_to_temp` 才引入冲突。本方案把这一步换回"不碰大漠"，**`TextMonitor` / `start_text_watcher` / 事件中断行走 这套架构一行不动**。

#### 选型对比

| | 大漠 dx2 Capture（现状） | PrintWindow + PW_RENDERFULLCONTENT | **WGC**（选定） |
|---|---|---|---|
| 后台遮挡 / 屏幕外 | ✅ | ✅ | ✅ |
| 对游戏进程影响 | ❌ 卡帧、撕注入锁 | 无 | 无 |
| 单次开销（1280×720） | 卡游戏一帧 | 5~15ms CPU（整客户区 GDI 拷贝） | 帧到达 ≈ 0，回读 1~3ms |
| 可持续帧率 | 不可接受 | 5~10 fps | 60 fps |
| 渲染路径兼容 | dx 钩点相关 | flip 模型交换链会黑屏 | 全覆盖（blt/flip/DComp/OpenGL/layered） |
| 系统要求 | — | Win 8.1+ | Win 10 1903+（去黄边框需 2004+） |
| 新增依赖 | — | 无（ctypes，`visual.py` 已有实现） | `windows-capture`（Rust/pyo3，依赖 numpy + opencv，主环境已有） |
| API 性质 | — | 未正式文档化的 flag | 微软正式 API，长期支持 |

选 WGC 的理由：零打扰 + 性能余量，可以承接第二阶段全项目截图统一（含战斗状态 20+ fps 连续截帧，PrintWindow 撑不住）。PrintWindow 不作为备选保留——项目只维护一种截图方式。

#### 依赖（已完成）

- `windows-capture==2.0.1`（2026-08-08 发布，已 `uv add` 固定进主环境 `.venv`；`requires_python >= 3.9`，依赖 `numpy`、`opencv-python`——主环境已有 numpy 2.5.1 / opencv 5.0.0）。**已确认该版本 `WindowsCapture.__init__` 含 `window_hwnd` 参数**
- **只装到主环境 `.venv`**，禁止进 `.venv-dm`
- 多开机器上存在多个 `Warcraft III` 同名窗口（KK 残留闲置进程），库的 `window_name` 是标题子串匹配、命中哪个实例不确定，截错实例的症状与"截图失效"完全相同。**必须用 `war3.find_game_window()` 返回的 hwnd 建会话**，不能按标题

#### 原则：不做兜底 / 兼容 / 回退

- 后台模式截图**只有 WGC 一条路**。不提供 `capture = "dm"` 之类可选项，不在 WGC 失败时退回大漠 Capture、PrintWindow 或前台模式——大漠 dx 截图本身就是问题源，退回去等于把 bug 藏起来
- WGC 会话建不起来、帧流停止、窗口关闭、客户区偏移算不出来 → **直接抛异常终止任务**，日志写清原因（缺 `window_hwnd`、系统版本不足、窗口最小化/锁屏帧过期等），由人处理环境问题
- 环境要求（Win10 1903+、窗口不最小化、挂机机不锁屏）作为**前置条件**写进文档和启动自检，不满足就报错，不在运行期绕

#### 设计

**1. WGC 截图器（`runner/driver/` 新增 `wgc_capture.py`）**

```python
class WgcCapture:
    def __init__(self, hwnd: int, min_interval_ms: int): ...
    def grab_client(self, bbox: tuple[int, int, int, int]) -> np.ndarray: ...  # 失败抛 CaptureError
    def close(self) -> None: ...
```

- `bbox` 统一为**客户区坐标**，与现有 OCR 配置 `area_coords` 一致，无需转换
- 单一实现，不做 Protocol/多后端抽象——项目截图只有 WGC 一种

**2. `WgcCapture` 实现要点**

- 一个 hwnd 一个常驻会话：`WindowsCapture(window_hwnd=hwnd, cursor_capture=False, draw_border=False, minimum_update_interval=<监测间隔 ms>)`，`start_free_threaded()` 在库自己的线程收帧；同一 hwnd 多处使用共用一个会话（hwnd → 会话的引用计数）
- `on_frame_arrived` 只做一件事：把最新帧（BGRA ndarray）拷一份存到 `self._latest`（带锁 + 时间戳），不做 OCR、不做裁剪。`grab_client` 从 `_latest` 取帧再裁 bbox，调用方线程做 OCR
- **WGC 抓的是整个窗口矩形（含标题栏/边框）**，需要用 `GetWindowRect` 与 `ClientToScreen(0,0)` 算客户区在帧内的偏移，`grab_client` 裁剪时加上该偏移。窗口位置不动、尺寸由 `set_client_size` 固定，偏移算一次缓存即可；帧尺寸变化时重算
- 以下情况 `grab_client` **抛 `CaptureError`**，不返回 None、不静默重试：
  - 会话未启动 / `on_closed` 已触发（窗口关闭）
  - `_latest` 时间戳超过 `2 × 监测间隔`：窗口已停止出帧（最小化 / 锁屏 / RDP 断开），报"WGC 帧流停止"，避免拿冻结帧反复 OCR
  - 客户区偏移 + bbox 超出帧范围（偏移算错或窗口尺寸不符）
- `close()` 显式调用（`capture_control.stop()`），放在 `TextMonitor.stop()` / 任务结束处；进程退出用 `atexit` 收尾（这是资源释放，不是业务兜底）

**3. OCR 入口增加 ndarray 通路（`inference/local.py`）**

- 现有 `ocr_from_file` / `ocr_lines_from_file` 走"存盘 → `Image.open`"，WGC 已经拿到 ndarray，不该再落盘
- 新增 `ocr_from_array(img: np.ndarray) -> str` 与 `ocr_lines_from_array(img, merge_lines)`，内部复用 `_ocr`，BGRA → RGB 转换在此处做
- `worker.py` 子进程版本同步补一份（如仍在用）

**4. 监测线程接入（`runner/business/war3/text_monitor.py`）**

- `_ocr_region_text(ocr_cfg, hwnd)` 改为：`wgc.grab_client(area_coords)` → `ocr_from_array`。**删除**原来的 `self.ocr_text(self.dm, ...)` 大漠截图路径，不保留分支、不读配置切换
- `TextMonitor.start(hwnd)` 创建/复用 `WgcCapture`，`stop()` 关闭
- `start_text_watcher` 同样接入（无尽模式 `_start_boss_death_watcher` 在用）

**5. 主线程同步 OCR（`wait_for_text` / `wait_for_any_text`）**

- 也走 `_ocr_region_text`，自动受益：主线程的 OCR 也不再触发 dx2 Capture，接取/交任务阶段的卡帧同样消失
- 大漠 `find_pic` / `find_color` / `get_color` 本步暂不动（主线程串行、低频），在第二阶段统一迁到 WGC 帧上的 numpy 计算（见下）

#### 改动清单（已实施）

| 文件 | 改动 |
|---|---|
| `pyproject.toml` / `uv.lock` | `windows-capture==2.0.1`（主环境） |
| `runner/driver/wgc_capture.py` | 新增：`WgcCapture`（整窗/客户区取帧、save 存盘、`on_closed`、帧过期检测、客户区偏移计算）、hwnd → 会话引用计数（`acquire`/`release`）、`atexit` 收尾 |
| `utils/exception_handler.py` | 新增 `CaptureError` |
| `inference/local.py` | 新增 `ocr_from_array` / `ocr_lines_from_array`（BGRA→RGB），复用 `_merge_ocr_result` |
| `runner/business/war3/text_monitor.py` | `_ocr_region_text` 改走 WGC（`grab_client` → `ocr_from_array`），删大漠截图路径；新增 `WatchEvent`（error 字段）；`TextMonitor` 加 `error`/`on_error`，出错线程退出并在 watch/wait_for/wait_for_any/latest/stop 抛出；`start_text_watcher/stop_text_watcher` 管理会话生命周期 |
| `runner/tasks/war3/jiubing2/base.py` | `_make_monitor` 传 `on_error=self._on_monitor_error`（set stop_event 加速中断）；`_run_loop`/`_run_multi_loop` 的 `except StopTaskError` 分支检查 `monitor.error` 并上抛 |
| `runner/tasks/war3/jiubing2/others/patrol_loot.py` | 同上：`on_error` + `except StopTaskError` 检查 |
| `runner/tasks/war3/jiubing2/others/upgrade_stigmata.py` | `except StopTaskError` 分支检查 `monitor.error` 并上抛 |
| `config/data/war3/war3.toml` | 新增 `wgc_min_interval_ms = 100`；`bind_background.display` 注释更新（仅服务大漠找图找色，OCR 截图走 WGC） |
| `tests/manual/test_war3_bind_probe.py` | 并发截图压力默认走生产路径（`war3._ocr_region_text` WGC+OCR）；`--capture-dm` 用旧 dm.Capture 对照复现旧症状（验证完成后删除）；新增 `--wgc-dump`（绑定态抓整窗+prompt 区域存盘）、`--mouse` |
| `tests/manual/test_wgc_smoke.py` | 新增：对任意窗口建会话、取帧、裁客户区、存盘的冒烟脚本（已实测通过：首帧 0.27s，整客户区抓帧 1.7ms，extended_frame 偏移正确） |
| `AGENTS.md` | 已更新"待实施方案"为 WGC 方案并注明不做兜底/回退 |
| `inference/worker.py` | 无需改动——实际走的是 `LocalInferenceClient`（进程内），worker 子进程版本不在使用 |

不动的部分：`atomic/base.py`、`patrol_loot.py`、`upgrade_stigmata.py`、`endless_runner.py` 的 monitor 参数链与事件中断逻辑全部保留（只加了 `except StopTaskError` 分支的错误上抛）。

#### 实机冒烟结果（2026-09-14，`test_wgc_smoke.py --watch`）

| 场景 | 结果 |
|---|---|
| 大部分移出屏幕 | 最大帧龄 1000ms，0 次 CaptureError ✅ |
| 完全遮挡 | 最大帧龄 219ms，0 次 CaptureError ✅ |
| 最小化 | 会话启动即 `CaptureError`（fail-fast，符合设计）✅ |
| 锁屏（Win+L） | 锁屏期间帧流停止（帧龄涨至 20s+），解锁后自动恢复 ✅→前置条件 |

确认：WGC 帧流在锁屏/RDP 断开期间会停止，窗口与会话不死亡，解锁后自动恢复。
**挂机机前置条件：war3 窗口不最小化 + 系统不锁屏**（屏幕关闭省电无碍，禁的是
`Win+L`/自动锁屏/组策略锁屏超时）。锁屏发生时 `grab_client` 在 stale 阈值
（默认 2s）后抛 `CaptureError` 终止任务，不会拿冻结帧误跑。

#### 风险与约束

| 风险 | 说明 / 对策 |
|---|---|
| 窗口最小化 | DWM 不再合成，WGC 帧流停止 → `CaptureError` 终止任务（2026-09-14 实测：启动即报）。前置条件：KK 多开时 war3 窗口只能被盖住，不能最小化 |
| 锁屏 / RDP 断开 | 2026-09-14 实测：锁屏期间帧流停止、解锁后自动恢复。前置条件：挂机机器不锁屏（屏幕关闭省电无碍）；运行期不做回退 |
| 黄色边框 | Win10 1903~1909 无法关闭；2004+ `draw_border=False` 生效。挂机场景可接受 |
| `window_hwnd` 参数 | 需核对 PyPI 固定版本是否包含；无则该版本不可用，等待/换版本，不做改标题变通 |
| 帧内客户区偏移 | 帧含边框/标题栏，偏移算错 OCR 区域整体错位。探针 `--wgc-dump` 先目测再接入；越界抛 `CaptureError` |
| DPI 缩放 | WGC 返回物理像素；主进程需 Per-Monitor DPI aware，否则 `GetWindowRect` 是逻辑像素与帧不匹配。现有 `set_client_size` 已在物理像素工作，沿用 |
| 库稳定性 | `windows-capture` 仍在活跃迭代，API 偶有 breaking change → 固定版本；早期版本有 stop 卡死 issue → `close()` 加超时，超时记 error（资源释放问题，不影响业务判定） |

#### 验证

1. 探针 `--wgc-dump`：dx2 已绑定状态下抓一帧存盘，目测客户区偏移正确、OCR 区域内容正确
2. 探针 `--click`（WGC 并发截图压力）：三项解耦（①脚本→系统 ②系统→脚本 ③选择态点击）全过，**且游戏无周期性卡帧、光标不消失**
3. 对照 `--capture-dm --click` 复现旧症状，确认差异来自截图方式；对照完成后删除该选项
4. 城门骚扰任务后台端到端 ≥ 3 轮：接取提示、"已完成"中断行走、回 NPC 交任务全部命中
5. ~~真实挂机环境冻结帧测试~~ 已完成（2026-09-14，结果见上）：遮挡/屏幕外正常，最小化/锁屏报错。剩余可选：RDP 断开场景（与锁屏同理，挂机机以"RDP 断开前切控制台会话"规避）
6. 无尽模式 boss 死亡监测（`start_text_watcher` 路径）回归一轮

### 第二阶段（稍后做）：全项目截图统一为 WGC，删除其他截图代码

第一阶段验证通过后执行。目标：项目里**只剩 WGC 一种截图方式**，客户区坐标统一，删掉大漠 Capture、PrintWindow、PIL ImageGrab 三套并存的代码和随之而来的坐标转换/layered 特判。

#### 现有截图代码清单（待删除/迁移）

| 位置 | 现状 | 迁移 |
|---|---|---|
| `runner/driver/visual.py` `capture_region` / `capture_to_temp` | 大漠 `Capture` 存盘 | 删除；调用方改 `WgcCapture.grab_client` 拿 ndarray |
| `runner/driver/visual.py` `capture_region_printwindow` + `PW_*` 常量 + `is_layered_window` 分支 | KK layered 窗口 PrintWindow，含临时解绑/重绑 | 删除；WGC 原生支持 layered 窗口 |
| `runner/driver/visual.py` `find_pic` / `find_color` / `get_color` | 大漠 dx2 钩子找图找色 | 改为 WGC 帧上的 numpy/cv2 计算（`matchTemplate` / 颜色容差比对）；接口签名与返回值保持，调用方不动 |
| `runner/driver/screenshot.py` `save_screenshot` / `save_active_window_screenshot` | 大漠 Capture，屏幕坐标 | 改为按 hwnd 用 WGC 抓整窗存盘，参数改 hwnd + 客户区 bbox |
| `runner/business/base.py` `ocr_text` / `ocr_lines` | `dm.capture_to_temp` → 存盘 → `ocr_from_file` | 改 `grab_client` → `ocr_from_array`，不再落盘；去掉 `bind_window` 包裹（截图不再需要绑定） |
| `inference/local.py` `_ocr_screen` / `ocr_screen` / `ocr_lines`（ImageGrab，屏幕坐标） | 前台屏幕截图 | 删除；统一走 `*_from_array` |
| `inference/local.py` `capture_and_detect_chests` / `capture_and_predict_combat`（ImageGrab） | 宝箱检测 / 战斗状态连续截帧 | 删除 ImageGrab 入口，`detect_chests` / `predict_combat_batch` 接收 WGC 帧；战斗状态线程直接从 `WgcCapture._latest` 取帧，不再自建 ImageGrab 线程 |
| `inference/worker.py` 对应的 ImageGrab 子进程版本 | 同上 | 同步删除/迁移 |
| `runner/tasks/war3/jiubing2/others/upgrade_stigmata.py:330` 附近 | ImageGrab + 手动客户区→屏幕坐标转换 | 改 `ocr_lines_from_array`，删坐标转换 |
| `runner/tasks/war3/jiubing2/others/patrol_loot.py:239 / :486` | ImageGrab 独立线程 / 全屏截图 | 接 WGC 帧 |
| `runner/business/kk/*`、`runner/team/*` 中的 `ocr_text` / `ocr_lines` / `save_screenshot` 调用 | 经 `business/base.py` | 随 `business/base.py` 迁移；`force_refresh_layered` 是否仍需保留待实测（它解决的是 Qt 后台不重绘，与截图方式无关；若 WGC 帧同样陈旧则保留） |
| `runner/business/war3/window_manager.py` `find_game_window(capture=True)` 等调试截图 | 大漠 | 随 `screenshot.py` 迁移 |

#### 顺带的收益（需实测确认）

- 大漠不再承担任何截图职责后，`bind_background.display` 可以从 `dx2` 改为 `normal`，**彻底不挂 dx 渲染钩子**，只保留 `mouse`/`keypad` 注入通道。需用探针确认 `dx.mouse.*` 系鼠标模式不依赖 display=dx 才能生效
- 前台/后台模式在截图上不再有区别，`bind_foreground`/`bind_background` 只剩输入通道参数
- AGENTS.md "待办：统一截图方式，消除 ImageGrab 坐标转换" 三项全部关闭；"Layered window 刷新"一节里"截图继续用大漠 Capture（gdi2/dx2）"的表述同步更新
- 大漠 bind 与截图解耦后，"大漠 COM 非线程安全"不再约束截图线程（战斗状态检测线程的重构障碍消失）

#### 执行顺序与落地状态（2026-09-14 已完成代码改造）

1. ✅ `WgcCapture` 补 `grab_window()` / `save()` / `for_hwnd()`（常驻会话）/ `grab_client_rgb()` / `client_size()`
2. ✅ `visual.py` 重写：`find_pic`/`find_pics`/`find_color`/`get_color`/`capture_region`/`capture_to_temp` 全部走 WGC 帧 numpy 实现（`sliding_window_view` 分块模板匹配，delta_color 每通道容差、sim 为容差内像素占比，颜色串按大漠 RRGGBB/RGB 序解析）；PrintWindow 全部删除；本地自测：模板自匹配命中原位、精确找色/容差找色正确
3. ✅ `business/base.py`：`ocr_lines`/`ocr_text` 签名改为 `(hwnd, ocr_cfg)`，WGC ndarray → `ocr_*_from_array`，不再 `bind_window` 包裹、不落临时文件；`ocr_kk_lines` 同步去掉 dm 参数；全部 10 个调用点已更新（hall/join_room/room_manager/multi_instance/leader/follower/window_manager/game_ui/jiubing2.base/patrol_loot）
4. ✅ `inference/local.py`：删 `ocr_screen`/`ocr_lines`/`capture_and_detect_chests`/`capture_and_predict_combat`/`predict_combat_batch` 及 ImageGrab import；新增 `detect_chests_from_array` / `predict_combat_from_arrays`
5. ✅ `inference/worker.py`：删全部 ImageGrab 命令（`ocr`/`ocr_lines`/`capture_and_*`），保留 `*_from_file`/`predict_combat` 文件入口（exe 打包用）
6. ✅ `patrol_loot`：战斗检测线程改 WGC 循环抓帧 + `predict_combat_from_arrays`，cancel_file 机制删除（同进程直接查 `_combat_check_running`）；`_find_all_chests` 改 `grab_client` 全客户区 + `detect_chests_from_array`，屏幕坐标转换删除
7. ✅ `upgrade_stigmata`：`read_stigmata_stats` 两段 OCR 改 `grab_client_rgb` + `ocr_lines_from_array`，手动屏幕坐标转换删除
8. ✅ `screenshot.py`：`save_screenshot`/`save_active_window_screenshot` 改 WGC；bbox 语义统一为客户区坐标；无绑定时用 `_last_bind_hwnd`（最近绑定目标）兜底，再没有才前台窗口
9. ✅ `window.py`：删 `_current_bind_params`（PrintWindow 重绑残留），加 `_last_bind_hwnd`
10. ✅ 探针 `--capture-dm` 对照组改直接调 `dm._com_call("Capture")`（`capture_to_temp` 已是 WGC 实现）

#### 待实机回归

- War3 后台端到端（`--task atomic.blackstone_gate_harassment --bg`），确认无卡帧、选择态点击正常
- 遮挡 / 移出屏幕场景下 find_pic / OCR / 宝箱 / 战斗检测回归
- 钓鱼找色：`find_color` 的颜色串按大漠 RRGGBB（RGB 序）解析，需实机确认与旧 dm.FindColor 一致
- KK 组队流程（`KK_TEST_NO_START_GAME=1`）回归
- `display=dx2` → `normal` 优化：需探针确认 dx.mouse.* 不依赖 display 钩子，未验证前保留 dx2

### 第三阶段：War3 多开窗口认领（2026-09-14 代码完成，待实机验证）

需求：同机两个 war3 各跑各自脚本，互不干扰、不错领窗口。

- `runner/driver/process_lock.py`：通用 `NamedMutex`（CreateMutexW + 非阻塞等待，
  锁持有到进程退出、崩溃自动释放）
- `window_manager.claim_war3_window(target_player)`：枚举 → 互斥锁认领（已认领跳过
  不发 token）→ 配置了 target_player 时向窗口发随机 token（gb+pid+随机hex）并
  OCR 聊天区 `[this.multi_instance].chat_area_coords`，从"玩家名：token"行提取
  归属名匹配；不匹配释放锁换下一个。认领后 `_claimed_hwnd`/`claimed_owner` 记录，
  `_find_war3_hwnd` 改为返回认领 hwnd（IsWindow 校验），不再重新枚举
- `find_game_window`（background 模式）自动走认领流程；`War3Business.target_player`
  由任务侧从 `cfg["target_player"]`（顶层可继承键）注入
- 变体配置：完整复制任务 toml 改 `name`（如 `tasks/others/fishing_player_a.toml`），
  `target_player` 写在自己的 `[this]` 里；启动时传配置名参数
  `python -m ...fishing fishing_player_a`，任务按实际加载名读自己的配置段
- 冒烟脚本 `tests/manual/test_war3_claim.py`（`--player`/`--hold`）
- 待实机：聊天行格式（全角/半角冒号、名字分隔符）、token 上屏延迟、
  双脚本互斥认领回归、加载页兜底场景

### 已否决方案

**同步轮询**（原 `docs/review_reports/war3_monitor_sync_polling_plan.md`，已删除）
- 思路：删掉监测线程，OCR 并入主线程等待间隙同步轮询，所有 dm 调用串行
- 否决理由：
  1. 立论"并发 dm 是根源"不成立——bridge 已串行；真正的根源是 dx2 Capture 固有的卡帧/撕锁，同步轮询只是降低频率，每次截图仍卡一帧、光标闪一下
  2. 动 7 个业务文件、砍掉 `TextMonitor` 抽象；无尽模式 `_on_arrive` 施法期间完全失明，只靠 60s 兜底
  3. 以后任何"边操作边看画面"的需求（宝箱检测、战斗状态）都会撞同样的墙

**大漠 display 矩阵（dx3 / dx.graphic.*）**
- 全是进程内钩渲染，同步代价一样在；`gdi`/`gdi2` 对 D3D 黑图；`normal` 后台失效
- 未实测，但与"截图不能影响主流程"约束原理性冲突，不再投入

**`dm.input_guard()`**（已实测回退）
- `_io_lock` 包住关键输入序列防并发截图，持锁区段外仍周期性卡顿/丢光标
