# GameBot — 九种兵器2 自动化脚本系统

魔兽争霸3 RPG 地图「九种兵器2」的 Python 自动化脚本系统，自动完成日常/周常任务：钓鱼、无尽刷分、巡逻拾取、声望任务、成就/圣痕升级等。

## 环境要求

- **主环境**：Python 3.12（64 位，Web 服务器、OCR/AI 推理、模型训练），Windows 系统
- **大漠脚本环境**：Python 3.8（32 位，大漠插件 COM 要求），作为项目内工具使用
- **大漠插件**：版本 3.1233，DLL 放置在 `external/dm/` 目录下（不纳入版本控制）
- **依赖管理**：[uv](https://docs.astral.sh/uv/)

## 双环境隔离机制

项目使用两套完全隔离的 Python 环境，Web 是主项目，大漠脚本是工具：

| | 主环境 Python 3.12（.venv） | 大漠脚本环境 Python 3.8 32位（.venv-dm） |
|---|---|---|
| **用途** | Web 服务器、OCR/AI 推理、模型训练 | 大漠 COM 自动化脚本（runner） |
| **依赖管理** | `pyproject.toml` | `dm-requirements.txt` |
| **依赖** | fastapi、uvicorn、pydantic、rapidocr、onnxruntime、numpy | loguru、Pillow、pywin32、tomli |
| **启动命令** | `uv run python -m GameBot.web.server` | `.venv-dm/Scripts/python.exe main.py` |

跨环境调用：大漠脚本（3.8）通过 subprocess 启动主环境的 Python 运行推理子进程；Web 服务器（3.12）启动任务子进程时从 `base.toml [main].python_path` 读取 3.8 Python 路径。

## 安装

```bash
# 主依赖（Python 3.12，Web/OCR/AI）
uv sync

# 大漠脚本依赖（32 位 Python 3.8，与主环境隔离）
uv venv .venv-dm --python 3.8
uv pip install -r dm-requirements.txt --python .venv-dm

# 将 src/ 注册到 .venv-dm 的 site-packages（src 布局需要，仅需执行一次）
Set-Content -Path .venv-dm/Lib/site-packages/GameBot.pth -Value "$PWD\src" -Encoding ascii
```

## 运行

```bash
# 前端构建
npm run build --prefix src/GameBot/web/frontend

# Web服务器（主环境，FastAPI + Vue 3）
uv run python -m GameBot.web.server

# 大漠脚本任务（使用 .venv-dm 环境）
.venv-dm/Scripts/python.exe main.py --task fishing
.venv-dm/Scripts/python.exe -m GameBot.runner.tasks.war3.jiubing2.others.fishing
.venv-dm/Scripts/python.exe -m GameBot.runner.tasks.war3.jiubing2.others.patrol_loot
.venv-dm/Scripts/python.exe -m GameBot.runner.tasks.war3.jiubing2.endless.endless_single
.venv-dm/Scripts/python.exe -m GameBot.runner.tasks.war3.jiubing2.endless.endless
.venv-dm/Scripts/python.exe -m GameBot.runner.tasks.war3.jiubing2.reputation.daily_reputation
.venv-dm/Scripts/python.exe -m GameBot.runner.tasks.war3.jiubing2.achievements.personal
.venv-dm/Scripts/python.exe -m GameBot.runner.tasks.war3.jiubing2.others.upgrade_stigmata
```

## 任务列表

### 无尽任务

- **[多局无尽](docs/tasks/endless.md)** — 完整流程：KK 启动游戏 → War3 → 准备阶段 → 进皇宫 → 进无尽 → 循环 → 退出，多局自动循环
- **[局内无尽](docs/tasks/endless.md)** — 英雄已在无尽地图内，直接循环刷怪（准备阶段已完成）

### 声望任务

- **[每日声望](docs/tasks/reputation.md)** — 顺序编排：黑石城声望 → 转场至森之城 → 森之城声望，各 150 点
- **[黑石城声望](docs/tasks/reputation.md)** — 反复完成城门骚扰任务，按声望上限/每次收益反推次数
- **[森之城声望](docs/tasks/reputation.md)** — 反复完成迅猛野兽任务，按声望上限/每次收益反推次数

### 成就任务

- **[个人任务成就](docs/tasks/achievements.md)** — 反复完成城门骚扰任务直到达成指定次数

### 原子任务（由上层任务调度，不单独运行）

- **[迅猛野兽](docs/tasks/atomic.md)** — 森之城：走到狄安娜 → 接任务 → 沿路线杀怪 → OCR 检测完成 → 回 NPC 交任务
- **[城门骚扰](docs/tasks/atomic.md)** — 黑石城：走到守卫队长 → 接任务 → 沿路线骚扰 → OCR 检测完成 → 回 NPC 交任务

### 其他任务

- **[钓鱼](docs/tasks/fishing.md)** — 自动抛竿、找色检测中钩、OCR 检测钓鱼成功次数，支持快速/慢速两种模式
- **[刷装备](docs/tasks/patrol_loot.md)** — 路线循环杀怪，AI 检测地面宝箱，OCR 识别物品名称，自动拾取目标物品
- **[升级圣痕](docs/tasks/upgrade_stigmata.md)** — 交替执行城门骚扰（获取升级机会）与圣痕升级，直到所有词条达标

### 任务继承关系

```
AtomicLoopTask（基类：窗口绑定、OCR 预热、原子任务循环）
├── UpgradeStigmataTask     # 升级圣痕
└── PersonalAchievementTask  # 个人成就

ReputationTask（继承 AtomicLoopTask，增加声望上限反推次数）
├── BlackstoneReputationTask  # 黑石城声望
└── ForestReputationTask      # 森之城声望

DailyReputationTask（独立编排类，组合黑石城 + 森之城声望）
```

## 项目结构

```
GameBot/
├── main.py                        # 大漠脚本入口（运行在 .venv-dm 环境）
├── pyproject.toml                 # 项目元数据与主依赖（Python 3.12，Web/OCR/AI）
├── dm-requirements.txt            # 大漠脚本环境依赖（32 位 Python 3.8，独立于 pyproject.toml）
├── user_configs.json              # 用户配置覆盖
├── .python-version                # 主 Python 版本（3.12）
├── .gitignore
├── .windsurfrules                 # Windsurf 项目规则
├── .windsurf/workflows/           # Windsurf 工作流定义
│   ├── new-hero.md                #   新增英雄配置
│   ├── new-task.md                #   新增任务模块
│   └── train-model.md             #   训练模型流程
├── docs/
│   ├── config_inheritance.md      # 配置继承规则文档
│   └── tasks/                     # 任务详细文档
│       ├── fishing.md             #   钓鱼
│       ├── patrol_loot.md         #   巡逻拾取
│       ├── endless.md             #   无尽刷分（单局/多局）
│       ├── reputation.md          #   声望任务（每日/黑石城/森之城）
│       ├── atomic.md              #   原子任务（迅猛野兽/城门骚扰）
│       ├── upgrade_stigmata.md    #   升级圣痕
│       └── achievements.md        #   成就任务
├── external/
│   └── dm/                        # 大漠插件 DLL（dm.dll，不纳入版本控制）
├── data/                          # 训练数据集（截图样本，不纳入版本控制）
├── scripts/                       # 模型训练脚本
│   ├── collect_chest_samples.py   #   采集宝箱检测样本
│   ├── collect_combat_samples.py  #   采集战斗状态样本
│   ├── train_chest_detector.py    #   训练宝箱检测模型（YOLOv8 → ONNX）
│   ├── train_combat_model.py      #   训练战斗状态分类模型
│   └── models/                    #   训练用模型配置/权重
├── tests/                         # 测试
│   ├── test_config.py             #   配置系统单元测试
│   ├── test_chest_detect.py       #   宝箱检测测试
│   ├── bench_keypress.py          #   按键性能基准
│   ├── bench_find_color.py        #   找色性能基准
│   └── bench_display_mode.py      #   显示模式基准
└── src/GameBot/              # 源码
    ├── inference/                 # 推理子进程（主环境 3.12，被大漠脚本通过 subprocess 调用）
    │   ├── client.py              #   主进程端：管理子进程生命周期、JSON 通信
    │   ├── worker.py              #   子进程端：OCR、宝箱检测、战斗状态检测
    │   ├── chest_detector.py      #   宝箱检测（YOLOv8）
    │   ├── combat_detector.py     #   战斗状态分类
    │   └── ocr_compat.py           #   OCR 兼容层
    ├── runner/                    # 大漠脚本工具包（运行在 .venv-dm 32 位 Python 3.8）
    │   ├── dm_client.py           #   大漠插件 COM 封装（窗口绑定、找图找色、键鼠模拟）
    │   ├── resource_manager.py    #   资源路径管理
    │   ├── ui/                    #   脚本控制 UI
    │   │   ├── float_window.py    #     tkinter 置顶浮窗（停止按钮、运行计时）
    │   │   └── hotkey_listener.py #     全局热键监听（F7 启动 / F6 停止）
    │   ├── business/              #   业务逻辑层
    │   │   ├── base.py            #     业务基类
    │   │   ├── kk.py              #     KK 平台业务（启动游戏）
    │   │   ├── war3/              #     魔兽3通用操作（mixin 拆分）
    │   │   │   ├── core.py        #       War3Business 组合类
    │   │   │   ├── window_manager.py  #   窗口管理
    │   │   │   ├── input_controller.py#   输入控制（移动、传送、背包）
    │   │   │   ├── skill_controller.py#   技能施放、连招
    │   │   │   └── text_monitor.py    #   OCR 文字监测
    │   │   └── jiubing2/          #     九种兵器2业务逻辑
    │   │       ├── game_ui.py     #       游戏面板操作（技能、卡牌、神碎、圣痕）
    │   │       ├── combat_helper.py  #   战斗辅助（连招、物品、宠物）
    │   │       ├── scene_navigator.py # 场景导航（传送、进皇宫、进无尽）
    │   │       └── endless_runner.py  #   无尽循环编排
    │   └── tasks/                 #   任务编排
    │       ├── base.py            #     AtomicLoopTask / ReputationTask 基类
    │       ├── atomic/            #     原子任务（迅猛野兽、黑石门骚扰等）
    │       ├── endless/           #     无尽任务（单局、多局）
    │       ├── others/            #     其他任务（钓鱼、巡逻拾取）
    │       ├── reputation/        #     声望任务
    │       └── achievements/      #     成就任务
    ├── config/                    # TOML 配置系统（共享）
    │   ├── system/                # 配置加载引擎（依赖解析、继承合并、用户覆盖）
    │   └── data/                  # 配置文件（英雄、任务、场景、游戏机制）
    ├── web/                       # Web 配置端（主环境，FastAPI + Vite + Vue 3 + Element Plus + Pinia + VueUse + TypeScript）
    │   ├── server.py              # FastAPI 入口
    │   ├── api/                   # 后端 API 层
    │   │   ├── routes/            # 路由模块（init/schema/config/hero/task）
    │   │   ├── models.py          # Pydantic 请求/响应模型
    │   │   └── services.py        # 业务逻辑（TOML 读写、任务启停）
    │   ├── frontend/              # 前端源码（Vite + Vue 3 + Element Plus + Pinia + VueUse + TypeScript）
    │   │   ├── src/               # Vue 3 SFC 组件、Pinia stores、路由
    │   │   └── package.json       # 前端依赖
    │   └── dist/                  # 前端构建产物（不纳入版本控制）
    ├── resources/                 # 静态资源
    │   ├── fonts/                 #   OCR 字库文件
    │   ├── images/                #   找图用 BMP 模板（小地图信号、钓鱼状态等）
    │   └── models/                #   ONNX 模型权重
    │       ├── chest_detector.onnx    # YOLOv8 宝箱检测模型
    │       └── combat_status.onnx     # 战斗状态分类模型
    └── utils/                     # 工具（共享）
        ├── logger.py              #   日志（loguru）
        └── exception_handler.py   #   自定义异常 + retry 装饰器
```

## 配置系统

- 配置文件为 TOML 格式，位于 `src/GameBot/config/data/`
- 通过 `dependencies = ["heroes.hxd", "jiubing2"]` 声明依赖关系，dependencies负责把依赖的TOML加载到cfg树中，代码负责从各命名空间分别取值
- 加载机制：深度优先后序展开依赖，后加载的同名可继承节点深度合并（未覆盖的字段从父配置继承），`[hero]` 特殊做浅合并（子键完全覆盖）
- 英雄配置互斥：`heroes.*` 中最后加载的英雄独占生效
- 命名空间：带前缀的节点（如 `[tasks.patrol_loot]`）不可继承，不带前缀的（如 `[hero]`）可继承
- 用户覆盖：`user_configs.json` 用于覆盖英雄背包、目标物品、巡逻轮数等
- 详细规则参见 [docs/config_inheritance.md](docs/config_inheritance.md)

## 技术要点

- **32/64 位跨进程推理**：大漠脚本（32 位 Python 3.8）通过行式 JSON 与主环境（64 位 Python 3.12）推理子进程通信，运行 ONNX 模型和 RapidOCR
- **OCR 文字监测**：常驻后台线程实时监测游戏文字，支持事件中断移动等待
- **AI 模型检测**：自训练 YOLOv8 宝箱检测 + 战斗状态分类模型（ONNX 格式）
- **浮窗控制**：tkinter 置顶浮窗 + F7/F6 全局热键，运行中可随时停止

## 测试

```bash
# 配置系统单元测试（主环境）
uv run python -m pytest tests/test_config.py -v

# 性能基准测试（大漠脚本环境）
.venv-dm/Scripts/python.exe tests/bench_keypress.py
.venv-dm/Scripts/python.exe tests/bench_find_color.py
.venv-dm/Scripts/python.exe tests/bench_display_mode.py
```

## 许可证

私有项目，未公开发布。