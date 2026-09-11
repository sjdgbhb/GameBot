---
description: 训练模型 — 采集样本 → 标注 → 训练 → 导出 ONNX 的完整流程
---

# 训练模型工作流

当用户需要训练或更新 AI 检测模型时，按以下步骤操作。

项目中有两个 AI 模型：
- **宝箱检测模型**（YOLOv8 目标检测）— 检测地面宝箱位置
- **战斗状态模型**（CNN 二分类）— 判断英雄是否在战斗中

## 1. 确认训练目标

向用户确认要训练哪个模型：
- **宝箱检测** → 走步骤 2A
- **战斗状态** → 走步骤 2B

## 2A. 宝箱检测模型流程

### 2A-1. 采集样本

运行采集脚本（32位 .venv 环境）：
```bash
uv run python scripts/collect_chest_samples.py
```
- 在游戏中摆放宝箱（尤其是重叠场景）
- 脚本每隔 1-10 秒自动截图，保存到 `data/chest_samples/images/`
- 按 Ctrl+C 停止
- 建议采集 500+ 张

### 2A-2. 标注样本

使用 x-anylabeling 工具标注：
- 标签格式：YOLO（每行 `class xc yc w h`，归一化坐标）
- 标签保存到 `data/chest_samples/labels/`
- 类别：0 = chest
- 创建 `data/chest_samples/classes.txt`，内容为 `chest`

### 2A-3. 训练模型

使用 64 位 Python 运行（需安装 ultralytics）：
```bash
F:\program\python\python312\python.exe scripts/train_chest_detector.py
F:\program\python\python312\python.exe scripts/train_chest_detector.py --epochs 200 --imgsz 1280 --batch 8
```
- 预训练权重在 `scripts/models/yolov8m.pt`
- 训练结果保存在 `data/chest_samples/dataset/runs/`
- 训练完成后自动导出 ONNX 到 `src/GameBot/resources/models/chest_detector.onnx`

### 2A-4. 验证模型

```bash
uv run python tests/test_chest_detect.py
```
在游戏中观察宝箱检测效果，如不理想可增加样本或调整参数重新训练。

## 2B. 战斗状态模型流程

### 2B-1. 采集样本

运行采集脚本（32位 .venv 环境）：
```bash
uv run python scripts/collect_combat_samples.py --hero {英雄名}
uv run python scripts/collect_combat_samples.py --hero hxd --max 100 --interval 1.0
```
- 脚本利用帧差法 + 红色像素过滤自动标注
- 战斗中截图保存到 `data/combat_samples/combat/{英雄名}/`
- 非战斗截图保存到 `data/combat_samples/non_combat/{英雄名}/`
- 按 Ctrl+C 停止
- 切换英雄后重新运行，指定 `--hero` 参数

### 2B-2. 训练模型

使用 64 位 Python 运行（需安装 torch）：
```bash
F:\program\python\python312\python.exe scripts/train_combat_model.py
```
- 训练完成后自动导出 ONNX 到 `src/GameBot/resources/models/combat_status.onnx`
- 模型输入：87x61 RGB 图像，输出：战斗概率（0~1）

### 2B-3. 验证模型

在游戏中运行巡逻拾取或无尽任务，观察战斗状态检测是否准确。

## 3. 注意事项

- 采集脚本用 uv run 运行（大漠经 dm_bridge 子进程调用）
- 训练脚本用 64 位 Python 运行（需要 torch/ultralytics，不能在 32 位环境运行）
- ONNX 模型文件提交到版本控制，.pt 权重文件不提交（已在 .gitignore 中忽略）
- 训练数据（data/）不提交到版本控制
