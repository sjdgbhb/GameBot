# War3 后台开发记录

> 持续更新的后台模式（`bind_mode = "background"`）开发记录。每个条目记录：解决的问题、根因、方案、改动清单、验证方式。
> 绑定参数矩阵等实测结论同步维护在 [AGENTS.md](../../AGENTS.md)。

---

## 2026-09-12 OCR 监测截图改用 WGC，消除 dx2 Capture 对鼠标注入的干扰

> 状态：**方案已定，待实施** | 关联任务：`atomic/blackstone_gate_harassment.toml`（城门骚扰，后台模式）

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

#### 依赖

- `windows-capture`（PyPI，当前最新 2.0.1，`requires_python >= 3.9`，依赖 `numpy`、`opencv-python`——主环境 `.venv` 已有 numpy 2.5.1 / opencv 5.0.0）
- **只装到主环境 `.venv`**，禁止进 `.venv-dm`
- 用 `uv add` 固定到发布 ≥ 7 天的版本；实施前确认该版本的 `WindowsCapture.__init__` 含 `window_hwnd` 参数（main 分支已有，PyPI 发布版需核对）。**没有该参数的版本不可用**，不做改标题等变通
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

#### 改动清单

| 文件 | 改动 |
|---|---|
| `pyproject.toml` | `uv add windows-capture==<固定版本>`（主环境） |
| `runner/driver/wgc_capture.py` | 新增：`WgcCapture`、`CaptureError`、hwnd → 会话引用计数 |
| `inference/local.py` | 新增 `ocr_from_array` / `ocr_lines_from_array`；抽 `_ocr_impl(ndarray)` |
| `inference/worker.py` | 同步新增数组入口（若子进程模式仍在用） |
| `runner/business/war3/text_monitor.py` | `_ocr_region_text` 改走 WGC，删大漠截图路径；`TextMonitor.start/stop`、`start_text_watcher/stop_text_watcher` 管理会话生命周期 |
| `config/data/war3/war3.toml` | `[this.bind_background]` 注释更新：display 仅用于大漠找图找色，截图走 WGC；不新增可选项 |
| `tests/manual/test_war3_bind_probe.py` | 监测压力改为 WGC 截图（旧 dm 截图压力仅保留 `--capture-dm` 用于对照复现，验证完成后删除）；新增 `--wgc-dump` 抓一帧存盘用于目测 |
| `AGENTS.md` | 更新"并发 dx2 Capture 会撕开鼠标注入锁"条目：待实施方案改为本方案，链接本文 |
| `docs/modules/driver.md` / `docs/modules/business.md` | 补 WGC 截图一节 |

不动的部分：`atomic/base.py`、`jiubing2/base.py`、`patrol_loot.py`、`upgrade_stigmata.py`、`endless_runner.py` 的 monitor 参数链与事件中断逻辑全部保留。

#### 风险与约束

| 风险 | 说明 / 对策 |
|---|---|
| 窗口最小化 | DWM 不再合成，WGC 帧流停止 → `CaptureError` 终止任务。前置条件：KK 多开时 war3 窗口只能被盖住，不能最小化 |
| 锁屏 / RDP 断开 | DWM 系方案共同风险，有反馈锁屏后帧流停滞。**必须在真实挂机环境跑一次冻结帧测试**；若确认停滞，前置条件加"挂机机器不锁屏 / RDP 断开前切控制台会话"，运行期不做回退 |
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
5. 真实挂机环境冻结帧测试：被遮挡 / 移出屏幕 / 锁屏 / RDP 断开 各持续 5 分钟，检查 `_latest` 时间戳持续更新
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

#### 执行顺序

1. `WgcCapture` 加整窗抓帧 + 存盘接口（`grab_window()` / `save()`），供调试截图使用
2. `find_pic` / `find_color` / `get_color` 的 numpy 实现 + 与大漠结果的对照测试（同一帧、同一模板/颜色，结果一致后才切）
3. `business/base.py` OCR 入口切换 → KK 端组队流程（`KK_TEST_NO_START_GAME=1`）回归
4. `inference` ImageGrab 入口删除 → 圣痕面板、宝箱检测、战斗状态检测逐个迁移并回归
5. `screenshot.py` 调试截图切换
6. 删除 `visual.py` 大漠/PrintWindow 截图代码、`is_layered_window` 分支、`_current_bind_params` 重绑逻辑
7. 探针验证 `display=normal` 可行后改配置
8. 更新 `docs/modules/driver.md` / `inference.md` / AGENTS.md

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
