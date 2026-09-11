# 开发流程

> 本文档整合了环境搭建、分支管理、提交规范、CI 等开发流程内容。

## 开发环境搭建

```bash
# 克隆仓库
git clone git@github.com:sjdgbhb/GameBot.git
cd GameBot

# 主依赖（Python 3.12，Web/OCR/AI）
uv sync

# 大漠脚本依赖（32 位 Python 3.8，与主环境隔离）
uv venv .venv-dm --python 3.8
uv pip install -r dm-requirements.txt --python .venv-dm

# 将 src/ 注册到 .venv-dm 的 site-packages（src 布局需要，仅需执行一次）
Set-Content -Path .venv-dm/Lib/site-packages/GameBot.pth -Value "$PWD\src" -Encoding ascii

# 前端构建
npm run build --prefix src/GameBot/web/frontend
```

详细环境说明参见 [README.md](../../README.md)。

## 分支管理策略

采用简化的 Git Flow，适合个人/小团队：

| 分支 | 用途 | 命名规则 |
|------|------|----------|
| `main` | 稳定发布版本，始终可运行 | 固定 |
| `dev` | 日常开发集成分支 | 固定 |
| `feat/*` | 新功能开发 | 如 `feat/fishing-task`、`feat/new-hero` |
| `fix/*` | Bug 修复 | 如 `fix/ocr-crash` |
| `refactor/*` | 重构 | 如 `refactor/config-loader` |

### 核心原则
- `main` 只接受来自 `dev` 的合并，保证稳定可运行
- 功能分支从 `dev` 拉出，完成后 PR 回 `dev`
- 正式发版时 `dev` → `main` + 打 tag
- **禁止**直接向 `main` 或 `dev` 推送，必须通过 PR 合并

### 日常工作流
```bash
# 1. 从 dev 创建功能分支
git checkout dev && git pull && git checkout -b feat/new-hero

# 2. 开发过程中频繁提交
git add -A && git commit -m "feat: 添加新英雄配置"

# 3. 功能完成后，推送并创建 PR 到 dev
git push -u origin feat/new-hero

# 4. PR 通过 CI 检查后合并到 dev

# 5. 准备发版时，dev 合并到 main 并打 tag
git checkout main && git merge dev
git tag -a v0.2.0 -m "新增钓鱼任务、巡逻拾取任务"
git push origin main --tags
```

## 提交信息规范

格式：`<type>: <描述>`

| 类型 | 说明 | 示例 |
|------|------|------|
| `feat` | 新功能 | `feat: 添加钓鱼自动抛竿检测` |
| `fix` | 修复 bug | `fix: 修复 OCR 识别中文乱码问题` |
| `refactor` | 重构（不改变功能） | `refactor: 重构配置加载引擎` |
| `docs` | 文档变更 | `docs: 更新钓鱼任务文档` |
| `chore` | 构建/配置等杂项 | `chore: 更新 .gitignore` |
| `test` | 测试相关 | `test: 添加配置继承单元测试` |

### 规则
- 描述用中文，简洁明了
- 一个提交只做一件事，避免混合多个无关变更
- 提交前确保代码可运行、测试通过

## Tag 版本管理

采用语义化版本（SemVer）：`v主版本.次版本.修订号`

| 版本号 | 何时使用 | 示例 |
|--------|----------|------|
| 主版本 (X) | 不兼容的架构变更 | `v1.0.0` → `v2.0.0` |
| 次版本 (Y) | 新功能、新任务模块、新英雄 | `v0.1.0` → `v0.2.0` |
| 修订号 (Z) | Bug 修复、小调整 | `v0.2.0` → `v0.2.1` |

## Pull Request 流程

1. 确保功能分支已推送且 CI 通过
2. 在 GitHub 上创建 PR，目标分支为 `dev`
3. PR 标题遵循提交信息规范
4. PR 描述说明变更内容和目的
5. CI 自动运行单元测试
6. 测试通过后合并

## CI

CI 配置位于 `.github/workflows/ci.yml`，在 push 和 PR 到 `main`、`dev` 时触发：
- 主依赖安装（`uv sync`）
- 单元测试（`uv run python -m pytest`）

## 测试

```bash
# 全部单元测试（主环境 3.12）
uv run python -m pytest

# 带覆盖率
uv run python -m pytest --cov

# 实机测试（需游戏窗口）
uv run python tests/manual/test_coords.py
```

测试标记：
- `unit`：单元测试
- `integration`：集成测试（真实文件 I/O，多模块协作）
- `manual`：需人工介入的手动测试（实机测试）
- `dm`：依赖大漠插件 COM
- `inference`：依赖 ONNX/AI 模型
- `web`：Web API 测试
- `config`：配置系统测试

## 运行命令速查

```bash
# Web服务器
uv run python -m GameBot.web.server

# 脚本任务（CLI）
uv run python main.py --task fishing
uv run python main.py --task team_task

# 脚本任务（直接模块）
uv run python -m GameBot.runner.tasks.war3.jiubing2.others.fishing
uv run python -m GameBot.runner.tasks.war3.jiubing2.others.patrol_loot
uv run python -m GameBot.runner.tasks.war3.jiubing2.endless.endless
uv run python -m GameBot.runner.tasks.war3.jiubing2.reputation.daily_reputation
uv run python -m GameBot.runner.tasks.war3.jiubing2.others.upgrade_stigmata
```

## 相关文档

- [架构总览](../architecture/overview.md) —— 理解项目结构后再开发
- [新增任务模块](new-task.md) / [新增英雄配置](new-hero.md) / [训练模型](train-model.md)
- [常见问题](troubleshooting.md)
