# Web 配置端

> 源码位置：`src/GameBot/web/`

## 职责

Web 端是项目的「可视化配置与任务启动面板」。它让用户通过浏览器编辑配置、
管理英雄、一键启动任务，而不需要手动改 TOML 文件或敲命令行。

采用前后端分离架构：
- **后端**：FastAPI，提供 REST API（配置读写、任务启停、英雄管理）
- **前端**：Vue 3 + TypeScript，schema 驱动的动态表单

## 对外能力

### 后端 API
- **初始化**：返回任务列表、英雄列表、物品定义、当前用户配置
- **任务 schema**：返回指定任务的表单 schema 和默认值（前端按 schema 渲染表单）
- **启动任务**：启动指定任务的子进程
- **查询运行中任务**：返回当前正在运行的任务列表
- **保存配置**：把用户配置写入 `user_configs.json`
- **英雄管理**：导出英雄配置、保存英雄物品栏、批量导入英雄

### 前端
- **首页**：任务列表，选择任务进入配置
- **任务配置页**：按 schema 动态渲染表单（英雄选择、物品栏网格、路线点列表、目标物品等）
- **英雄管理页**：英雄配置导出/导入、物品栏编辑

## 依赖关系

- **配置系统**：读写 `config/data/` 下的 TOML 和 `user_configs.json`
- **FastAPI + uvicorn**：后端框架
- **Pydantic**：请求/响应模型
- **前端**：Vite + Vue 3 + TypeScript + Element Plus + Pinia + VueUse + Axios

## 关键机制

### 前后端协作
后端返回 schema + 默认值，前端按 schema 渲染表单。
用户填写配置后，前端 POST 保存到 `user_configs.json`。
任务启动时，后端用 `subprocess.Popen` 启动任务模块子进程。

### 任务启动
- Web 端启动任务时，用主环境 Python（sys.executable）启动任务模块子进程
- 子进程通过 `python -m GameBot.runner.tasks.war3.jiubing2.{task_id}` 启动
- 子进程 stdout/stderr 写入 `logs/web_*.log`
- **注意**：这与 `main.py` 的 CLI 入口是并行入口，两者都调用 `load_task`，但路径推导逻辑不同

### 配置读写
- Web 端读写 `user_configs.json`（用户可调参数）
- 同时保存英雄默认物品栏到对应 `heroes/<id>.toml`
- 不直接修改任务 TOML（任务参数通过 user_configs 覆盖）

## 关键约束

### 任务停止
- 当前后端只提供查询运行中任务的接口，**没有提供停止任务的接口**
- 任务停止依赖子进程自行结束或外部 kill
- 如需 Web 停止任务，需新增实现

### 前端构建
- 前端源码在 `web/frontend/`，构建产物在 `web/dist/`（不纳入版本控制）
- 修改前端后需运行 `npm run build` 重新构建
- 后端静态文件服务指向 `web/dist/`

## 前端目录结构

```
web/frontend/src/
├── main.ts / App.vue        # 入口
├── router/                  # 哈希路由
├── views/                   # 三个主视图：首页/任务配置/英雄管理
├── stores/                  # Pinia stores：config/hero/task
├── api/                     # axios 客户端封装
├── components/form/         # 表单组件：英雄选择/物品栏网格/路线点列表/目标物品/表单渲染器
├── components/hero/         # 英雄导出/图库
└── composables/             # 组合式函数（如 useToast）
```

## 配置约定

| 配置项 | 位置 | 语义 |
|--------|------|------|
| `web.*` | web.toml | Web 服务器相关配置 |

## 禁忌

- ❌ 不要在后端代码中包含任务执行逻辑（通过子进程启动任务模块）
- ❌ 不要让前端直接读写 TOML 文件（通过后端 API）
- ❌ 不要忘记构建前端（修改前端后需 `npm run build`）

## 关联文档

- [配置系统](config.md) —— Web 端读写的配置文件
- [任务编排层](tasks.md) —— Web 端启动的任务模块
- [架构总览](../architecture/overview.md) —— Web 端在入口体系中的位置
