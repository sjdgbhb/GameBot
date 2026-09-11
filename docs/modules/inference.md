# 推理模块

> 源码位置：`src/GameBot/inference/`

## 职责

推理模块负责所有 AI 相关的识别能力：OCR 文字识别、宝箱目标检测、战斗状态分类。
它在主环境进程内直接加载模型并执行推理，不启动子进程（子进程版本仅用于 exe 打包场景）。

## 对外能力

向业务逻辑层提供三种推理能力：

- **OCR 文字识别**：输入截图区域或图片文件，输出识别到的文字行
  - 用于游戏内文字监测（任务完成提示、难度选项、玩家名等）
  - 使用 RapidOCR（ONNXRuntime 后端），不用大漠 OCR
- **宝箱检测**：输入全屏截图，输出宝箱位置框（YOLOv8 目标检测）
  - 用于巡逻拾取任务中检测地面宝箱
- **战斗状态分类**：输入英雄头像区域连续截帧，输出是否在战斗中（CNN 二分类）
  - 用于巡逻拾取任务中判断是否需要停止移动等待战斗结束

## 依赖关系

- **配置系统**：读取推理设备（cpu/gpu）、模型目录、各模型的参数（输入尺寸/置信度/阈值）
- **RapidOCR**：OCR 引擎（ONNXRuntime 后端）
- **ONNXRuntime**：AI 模型推理引擎
- **PIL**：图像处理（ImageGrab 截图、图像缩放）
- **共享工具**：日志

## 关键约束

### 进程内执行
- 推理在主环境（3.12）进程内直接执行，不启动子进程
- 模型懒加载：首次调用对应能力时才初始化引擎
- 全局单例：通过工厂获取唯一实例，避免重复加载模型

### OCR 参数固定
- 关闭分类分支、限制最长边 960（平衡速度与精度）
- 根据配置启用/禁用 CUDA

### 截图方式（待统一）
- 当前部分场景用 ImageGrab（屏幕坐标，需手动转换客户区→屏幕）
- 部分场景用大漠截图（客户区坐标，无需转换）
- 目标是统一为大漠截图，消除坐标转换（见 AGENTS.md 待办）

### 模型文件
- 宝箱检测模型：`resources/models/chest_detector.onnx`（YOLOv8）
- 战斗状态模型：`resources/models/combat_status.onnx`（CNN 二分类）
- 模型文件纳入版本控制，.pt 权重不纳入

## 配置约定

| 配置项 | 位置 | 语义 |
|--------|------|------|
| `inference.device` | base.toml | 推理设备：cpu 或 gpu |
| `inference.models_dir` | base.toml | ONNX 模型目录 |
| `chest.ai_conf` | jiubing2.toml | 宝箱检测置信度阈值 |
| `chest.ai_iou` | jiubing2.toml | 宝箱检测 NMS IoU 阈值 |
| `chest.ai_input_size` | jiubing2.toml | 宝箱检测模型输入尺寸 |
| `combat_status.ai_img_w/h` | jiubing2.toml | 战斗分类模型输入宽高 |
| `combat_status.ai_threshold` | jiubing2.toml | 战斗分类阈值 |
| `combat_status.frame_count` | jiubing2.toml | 战斗检测采样帧数 |
| `combat_status.frame_interval` | jiubing2.toml | 战斗检测采样间隔（秒） |

## 禁忌

- ❌ 不要在桥接子进程（3.8）中导入推理模块（仅主环境 3.12）
- ❌ 不要在业务代码中直接加载模型（通过推理客户端单例获取）
- ❌ 不要假设模型已加载（懒加载，首次调用会初始化）

## 关联文档

- [架构总览](../architecture/overview.md) —— 推理为什么在进程内执行
- [训练模型](../guides/train-model.md) —— 如何训练和更新 AI 模型
- [业务逻辑层](business.md) —— 推理的使用者
- [AGENTS.md](../../AGENTS.md) —— 截图方式统一的待办事项
