# GameBot — 九种兵器2 自动化脚本系统

魔兽争霸3 RPG 地图「九种兵器2」的 Python 自动化脚本系统，自动完成日常/周常任务：钓鱼、无尽刷分、巡逻拾取、声望任务、成就/圣痕升级等。

## 快速开始

```bash
# 1. 安装主依赖（Python 3.12，Web/OCR/AI）
uv sync

# 2. 安装大漠桥接依赖（32 位 Python 3.8，与主环境隔离）
uv venv .venv-dm --python 3.8
uv pip install -r dm-requirements.txt --python .venv-dm
Set-Content -Path .venv-dm/Lib/site-packages/GameBot.pth -Value "$PWD\src" -Encoding ascii

# 3. 构建前端
npm run build --prefix src/GameBot/web/frontend

# 4. 运行
uv run python -m GameBot.web.server          # Web 配置服务器
uv run python main.py fishing                 # CLI 运行任务（task 为位置参数，默认 fishing）
```

> 大漠插件 DLL 放置在 `external/dm/` 目录下（不纳入版本控制）。

## 运行命令

```bash
# Web服务器
uv run python -m GameBot.web.server
# 或安装后直接用注册的命令入口
GameBot-web

# 脚本任务（CLI，task 为位置参数，默认 fishing）
uv run python main.py fishing
uv run python main.py endless
uv run python main.py patrol_loot
uv run python main.py daily_reputation
uv run python main.py upgrade_stigmata
uv run python main.py paladin_wind_dragon
uv run python main.py ingame_special
uv run python main.py team_task

# 脚本任务（直接模块）
uv run python -m GameBot.runner.tasks.war3.jiubing2.others.fishing
uv run python -m GameBot.runner.tasks.war3.jiubing2.endless.endless
uv run python -m GameBot.runner.tasks.war3.jiubing2.others.patrol_loot
uv run python -m GameBot.runner.tasks.war3.jiubing2.reputation.daily_reputation
uv run python -m GameBot.runner.tasks.war3.jiubing2.others.upgrade_stigmata
uv run python -m GameBot.runner.tasks.war3.jiubing2.others.paladin_wind_dragon
uv run python -m GameBot.runner.tasks.war3.jiubing2.festival.ingame_special
uv run python -m GameBot.runner.tasks.war3.jiubing2.achievements.personal
```

## 任务列表

| 任务 | 说明 | 文档 |
|------|------|------|
| 多局无尽 | KK→War3→准备→进皇宫→进无尽→循环→退出，多局自动循环 | [endless.md](docs/tasks/endless.md) |
| 单局无尽 | 英雄已在无尽地图内，直接循环刷怪 | [endless.md](docs/tasks/endless.md) |
| 每日声望 | 黑石城声望 → 转场至森之城 → 森之城声望，各 150 点 | [reputation.md](docs/tasks/reputation.md) |
| 个人成就 | 反复完成城门骚扰任务直到达成指定次数 | [achievements.md](docs/tasks/achievements.md) |
| 钓鱼 | 自动抛竿、找色检测中钩、OCR 检测次数 | [fishing.md](docs/tasks/fishing.md) |
| 巡逻拾取 | 路线循环杀怪，AI 检测宝箱，OCR 识别物品 | [patrol_loot.md](docs/tasks/patrol_loot.md) |
| 升级圣痕 | 交替执行城门骚扰与圣痕升级，直到词条达标 | [upgrade_stigmata.md](docs/tasks/upgrade_stigmata.md) |
| 圣骑士风龙 | 检测技能图标就绪即施放，冷却自动跳过（后台挂机） | — |
| 局内特殊任务 | 每日声望（黑石+森之城）→ 森之城鱼点钓鱼（节日活动局内脚本） | — |
| 组队任务 | 多开协作框架，队长建房广播，队员自动加入 | [技术方案](docs/review_reports/技术方案_多开需求.md) |

## 文档导航

详细文档位于 [docs/](docs/README.md)，按四层组织：

| 层 | 内容 | 入口 |
|----|------|------|
| **架构层** | 架构总览、模块依赖关系 | [architecture/](docs/architecture/overview.md) |
| **模块层** | 各模块的上下文卡片（vibecoding 时只加载需要的） | [modules/](docs/modules/) |
| **领域知识** | 游戏机制、KK平台、大漠插件 | [domain/](docs/domain/) |
| **开发指南** | 开发流程、新增任务/英雄、训练模型、踩坑 | [guides/](docs/guides/) |

### 常用入口
- 了解项目架构 → [架构总览](docs/architecture/overview.md)
- 开发某个模块 → [模块卡片](docs/modules/) 中找到对应模块
- 理解游戏背景 → [游戏机制](docs/domain/game-mechanics.md)
- 新增功能 → [新增任务](docs/guides/new-task.md) / [新增英雄](docs/guides/new-hero.md)
- 开发规范 → [开发流程](docs/guides/development.md) / [常见问题](docs/guides/troubleshooting.md)

## 双环境隔离

项目使用两套完全隔离的 Python 环境：

| | 主环境 Python 3.12（.venv） | 大漠桥接环境 Python 3.8 32位（.venv-dm） |
|---|---|---|
| **用途** | Web 服务器、OCR/AI 推理、全部业务逻辑 | 大漠 COM 调用（仅 dm_bridge 子进程） |
| **依赖管理** | `pyproject.toml` | `dm-requirements.txt` |
| **依赖** | fastapi、rapidocr、onnxruntime、numpy | loguru、Pillow、pywin32、tomli |

跨环境调用：主环境（3.12）通过 dm_bridge 子进程（3.8）调用大漠 COM，推理在主进程内直接执行。
详见 [架构总览](docs/architecture/overview.md)。

## 测试

```bash
uv run python -m pytest tests/unit -v          # 单元测试
uv run python -m pytest tests/integration -v   # 集成测试
```

## 许可证

私有项目，未公开发布。
