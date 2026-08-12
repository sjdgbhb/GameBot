r"""
训练宝箱检测模型（YOLOv8）

使用 ultralytics YOLOv8m 训练宝箱目标检测模型，训练完成后导出 ONNX。
推理端用 onnxruntime（主环境 3.12 推理子进程）。

前置条件：
  1. 已用 x-anylabeling 标注图片，YOLO格式标签在 data/chest_samples/labels/
  2. 安装 ultralytics: pip install ultralytics

使用方法（用有 ultralytics 的 Python 运行，需先安装 ultralytics）:
  uv run python scripts/train_chest_detector.py
  uv run python scripts/train_chest_detector.py --epochs 200 --imgsz 1280

数据目录结构（已有）:
  data/chest_samples/
    images/*.jpg           # 截图
    labels/*.txt           # YOLO格式标注（每行: class xc yc w h，归一化）
    classes.txt            # 类别名称
"""
import os
import sys
import shutil
import argparse
import glob
import random

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "chest_samples")
IMAGE_DIR = os.path.join(DATA_DIR, "images")
LABEL_DIR = os.path.join(DATA_DIR, "labels")
DATASET_DIR = os.path.join(DATA_DIR, "dataset")
MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "src", "GameBot", "resources", "models"
)
ONNX_PATH = os.path.join(MODEL_DIR, "chest_detector.onnx")

VAL_RATIO = 0.2


def prepare_dataset():
    """将标注好的数据拆分为 train/val，生成 data.yaml。"""
    images = sorted(glob.glob(os.path.join(IMAGE_DIR, "*.jpg")) +
                    glob.glob(os.path.join(IMAGE_DIR, "*.png")) +
                    glob.glob(os.path.join(IMAGE_DIR, "*.bmp")))

    labeled = []
    for img_path in images:
        label_path = os.path.join(LABEL_DIR, os.path.basename(img_path).rsplit(".", 1)[0] + ".txt")
        if os.path.exists(label_path):
            labeled.append((img_path, label_path))

    if not labeled:
        print(f"错误: 未找到标注数据")
        print(f"  图片目录: {IMAGE_DIR}")
        print(f"  标注目录: {LABEL_DIR}")
        sys.exit(1)

    print(f"标注样本数: {len(labeled)}")

    # 清理旧 dataset 内容（保留 runs 目录）
    for sub in ("images", "labels", "data.yaml"):
        path = os.path.join(DATASET_DIR, sub)
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.isfile(path):
            os.remove(path)

    for split in ("train", "val"):
        os.makedirs(os.path.join(DATASET_DIR, "images", split), exist_ok=True)
        os.makedirs(os.path.join(DATASET_DIR, "labels", split), exist_ok=True)

    random.seed(42)
    random.shuffle(labeled)
    val_size = max(1, int(len(labeled) * VAL_RATIO))
    val_set = labeled[:val_size]
    train_set = labeled[val_size:]

    for img_path, label_path in train_set:
        shutil.copy2(img_path, os.path.join(DATASET_DIR, "images", "train", os.path.basename(img_path)))
        shutil.copy2(label_path, os.path.join(DATASET_DIR, "labels", "train", os.path.basename(label_path)))

    for img_path, label_path in val_set:
        shutil.copy2(img_path, os.path.join(DATASET_DIR, "images", "val", os.path.basename(img_path)))
        shutil.copy2(label_path, os.path.join(DATASET_DIR, "labels", "val", os.path.basename(label_path)))

    print(f"训练集: {len(train_set)}, 验证集: {len(val_set)}")

    yaml_path = os.path.join(DATASET_DIR, "data.yaml")
    with open(yaml_path, "w") as f:
        f.write(f"path: {DATASET_DIR}\n")
        f.write("train: images/train\n")
        f.write("val: images/val\n")
        f.write("names:\n  0: chest\n")
    print(f"data.yaml: {yaml_path}")
    return yaml_path


def train(yaml_path, epochs, imgsz, batch):
    from ultralytics import YOLO

    model = YOLO(os.path.join(os.path.dirname(__file__), "models", "yolov8m.pt"))
    results = model.train(
        data=yaml_path,
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        project=os.path.join(DATASET_DIR, "runs"),
        # 不指定 name，ultralytics 会自动递增: train, train2, train3...
        device=0,  # 自动使用 GPU，无 GPU 时 ultralytics 会回退 CPU
        patience=30,
        # 小数据集增强
        hsv_h=0.015,
        hsv_s=0.7,
        hsv_v=0.4,
        degrees=10.0,
        translate=0.1,
        scale=0.5,
        flipud=0.0,
        fliplr=0.5,
        mosaic=0.5,        # 降低，避免宝箱被缩太小
        mixup=0.0,         # 关闭，对小目标有害
        copy_paste=0.3,    # 开启，生成重叠宝箱场景
    )
    print(f"\n训练完成，最佳模型: {results.save_dir}")

    best_pt = os.path.join(results.save_dir, "weights", "best.pt")
    if not os.path.exists(best_pt):
        print(f"错误: 未找到 best.pt")
        sys.exit(1)

    os.makedirs(MODEL_DIR, exist_ok=True)
    best_model = YOLO(best_pt)
    best_model.export(format="onnx", imgsz=imgsz, simplify=True)
    exported = best_pt.replace(".pt", ".onnx")
    if os.path.exists(exported):
        shutil.copy2(exported, ONNX_PATH)
        print(f"ONNX 模型已保存: {ONNX_PATH}")
    else:
        print(f"错误: ONNX 导出失败，未找到 {exported}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="训练宝箱检测 YOLOv8 模型")
    parser.add_argument("--epochs", type=int, default=200, help="训练轮数（默认200，小数据集多训几轮）")
    parser.add_argument("--imgsz", type=int, default=1280, help="输入尺寸（默认1280）")
    parser.add_argument("--batch", type=int, default=8, help="batch size（默认8）")
    parser.add_argument("--skip-prepare", action="store_true", help="跳过数据准备（已准备好时）")
    args = parser.parse_args()

    if not args.skip_prepare:
        yaml_path = prepare_dataset()
    else:
        yaml_path = os.path.join(DATASET_DIR, "data.yaml")
        if not os.path.exists(yaml_path):
            print("错误: --skip-prepare 但 data.yaml 不存在")
            sys.exit(1)

    print(f"开始训练: epochs={args.epochs}, imgsz={args.imgsz}, batch={args.batch}")
    train(yaml_path, args.epochs, args.imgsz, args.batch)


if __name__ == "__main__":
    main()
