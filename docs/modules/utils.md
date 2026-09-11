# 共享工具

> 源码位置：`src/GameBot/utils/` + `src/GameBot/runner/resource_manager.py`

## 职责

共享工具层提供项目所有模块共用的基础设施：日志、异常体系、文件IO、资源路径管理。
这一层无状态、无业务逻辑，被所有上层模块依赖。

## 对外能力

### 日志（logger.py）
- 基于 loguru 的统一日志系统
- 控制台输出（带颜色）+ 每日轮转文件 + ERROR 单独文件
- 支持按脚本名切换日志文件
- 兼容 PyInstaller 打包模式（无控制台）

### 异常体系（exception_handler.py）
- 统一异常基类及具体异常（大漠错误/配置错误/资源未找到/任务超时/停止任务/窗口丢失）
- `retry` 装饰器：可配置重试次数、间隔、可捕获异常类型
- `safe_call` 装饰器：捕获异常并返回默认值（用于「失败可忽略」场景）
- 全局未捕获异常钩子：安装后捕获所有未处理异常，StopTaskError 视为正常停止

### 文件IO（file_io.py）
- TOML/JSON 文件加载辅助
- 失败时返回 None 并记录 debug 日志（不吞编程错误）
- 兼容 tomllib（3.11+）和 tomli

### 资源路径管理（resource_manager.py）
- 统一管理图片、字体等资源文件的目录定位
- 按图片名返回绝对路径（带缓存）
- 支持临时安装 Windows 字体（通过 GDI API）

## 依赖关系

- **配置系统**：读取日志目录、资源根目录、截图输出目录
- **loguru**：日志引擎
- **标准库**：tomllib/tomli、ctypes（字体安装）
- 无业务模块依赖（是最底层，被所有模块依赖）

## 关键约束

### 异常体系
- `StopTaskError` 是特殊的「正常停止」信号，全局钩子中不记录为错误
- `retry` 和 `safe_call` 只捕获指定异常类型，不吞编程错误（如 KeyError/AttributeError）

### 资源管理
- 图片路径带缓存，避免重复文件系统访问
- 字体临时安装通过 Windows GDI API，退出时应移除
- 资源目录结构：`<resources_path>/images/`（找图模板）、`<resources_path>/fonts/`（OCR字库）

## 配置约定

| 配置项 | 位置 | 语义 |
|--------|------|------|
| `paths.log_path` | base.toml | 日志输出目录 |
| `paths.resources_path` | base.toml | 资源根目录（images/fonts/models） |
| `paths.screenshot_path` | base.toml | 调试截图输出目录 |

## 禁忌

- ❌ 不要在工具层引入业务逻辑或业务模块依赖（会导致循环依赖）
- ❌ 不要用 print 输出日志（用 logger）
- ❌ 不要用裸 try/except 吞掉所有异常（用 retry/safe_call 或捕获具体异常）

## 关联文档

- [架构总览](../architecture/overview.md) —— 工具层在架构中的位置
- [驱动层](driver.md) —— 资源管理器的使用者（找图路径解析）
