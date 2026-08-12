"""
训练战斗状态分类模型（CNN）

使用 PyTorch 训练一个小型 CNN，分类英雄头像为 战斗/非战斗。
训练完成后导出 ONNX 模型，供主环境推理子进程用 onnxruntime 推理。

使用方法（用有 PyTorch 的 Python 运行，需先安装 torch）:
  uv run python scripts/train_combat_model.py

数据目录结构:
  data/combat_samples/
    combat/{hero}/*.bmp
    non_combat/{hero}/*.bmp
"""
import os
import sys
import glob
import random

import numpy as np
from PIL import Image
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "combat_samples")
MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src", "GameBot", "resources", "models")
ONNX_PATH = os.path.join(MODEL_DIR, "combat_status.onnx")

IMG_W, IMG_H = 87, 61
EPOCHS = 50
BATCH_SIZE = 16
LR = 1e-3
VAL_RATIO = 0.2


class CombatDataset(Dataset):
    def __init__(self, samples, labels):
        self.samples = samples
        self.labels = labels

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        img = self.samples[idx]
        label = self.labels[idx]
        return torch.from_numpy(img).float(), torch.tensor(label, dtype=torch.float)


class CombatCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(3, 16, 3, padding=1)
        self.conv2 = nn.Conv2d(16, 32, 3, padding=1)
        self.conv3 = nn.Conv2d(32, 64, 3, padding=1)
        self.pool = nn.MaxPool2d(2, 2)
        self.fc1 = nn.Linear(64 * 10 * 7, 128)
        self.fc2 = nn.Linear(128, 1)
        self.dropout = nn.Dropout(0.3)

    def forward(self, x):
        x = self.pool(F.relu(self.conv1(x)))
        x = self.pool(F.relu(self.conv2(x)))
        x = self.pool(F.relu(self.conv3(x)))
        x = x.view(x.size(0), -1)
        x = self.dropout(F.relu(self.fc1(x)))
        x = torch.sigmoid(self.fc2(x))
        return x.squeeze(-1)


def load_data():
    combat_files = glob.glob(os.path.join(DATA_DIR, "combat", "*", "*.bmp"))
    non_combat_files = glob.glob(os.path.join(DATA_DIR, "non_combat", "*", "*.bmp"))

    print(f"战斗样本: {len(combat_files)}, 非战斗样本: {len(non_combat_files)}")
    if len(combat_files) == 0 or len(non_combat_files) == 0:
        print("错误: 样本不足，请先采集样本")
        sys.exit(1)

    samples = []
    labels = []

    for f in combat_files:
        img = Image.open(f).convert("RGB").resize((IMG_W, IMG_H))
        arr = np.array(img).transpose(2, 0, 1) / 255.0
        samples.append(arr)
        labels.append(1)

    for f in non_combat_files:
        img = Image.open(f).convert("RGB").resize((IMG_W, IMG_H))
        arr = np.array(img).transpose(2, 0, 1) / 255.0
        samples.append(arr)
        labels.append(0)

    combined = list(zip(samples, labels))
    random.shuffle(combined)
    samples, labels = zip(*combined)

    val_size = int(len(samples) * VAL_RATIO)
    val_s, train_s = samples[:val_size], samples[val_size:]
    val_l, train_l = labels[:val_size], labels[val_size:]

    print(f"训练集: {len(train_s)}, 验证集: {len(val_s)}")
    return (
        CombatDataset(train_s, train_l),
        CombatDataset(val_s, val_l),
    )


def augment(img_tensor):
    if random.random() > 0.5:
        img_tensor = torch.flip(img_tensor, dims=[2])
    if random.random() > 0.5:
        img_tensor = img_tensor * (0.8 + random.random() * 0.4)
        img_tensor = img_tensor.clamp(0, 1)
    return img_tensor


def train():
    torch.manual_seed(42)
    random.seed(42)

    train_ds, val_ds = load_data()
    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"设备: {device}")

    model = CombatCNN().to(device)
    criterion = nn.BCELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=20, gamma=0.5)

    best_val_acc = 0
    best_state = None

    for epoch in range(EPOCHS):
        model.train()
        train_loss = 0
        for imgs, labels in train_loader:
            imgs, labels = imgs.to(device), labels.to(device)
            for i in range(imgs.size(0)):
                imgs[i] = augment(imgs[i])
            optimizer.zero_grad()
            outputs = model(imgs)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            train_loss += loss.item()

        model.eval()
        val_loss = 0
        correct = 0
        total = 0
        with torch.no_grad():
            for imgs, labels in val_loader:
                imgs, labels = imgs.to(device), labels.to(device)
                outputs = model(imgs)
                val_loss += criterion(outputs, labels).item()
                preds = (outputs > 0.5).float()
                correct += (preds == labels).sum().item()
                total += labels.size(0)

        val_acc = correct / total if total > 0 else 0
        print(f"Epoch {epoch+1}/{EPOCHS} | train_loss={train_loss/len(train_loader):.4f} | "
              f"val_loss={val_loss/len(val_loader):.4f} | val_acc={val_acc:.4f}")

        if val_acc >= best_val_acc:
            best_val_acc = val_acc
            best_state = model.state_dict().copy()

        scheduler.step()

    print(f"\n最佳验证准确率: {best_val_acc:.4f}")

    model.load_state_dict(best_state)
    model.eval()

    os.makedirs(MODEL_DIR, exist_ok=True)
    export_onnx(model, device)
    print(f"ONNX 模型已保存: {ONNX_PATH}")


def export_onnx(model, device):
    dummy = torch.randn(1, 3, IMG_H, IMG_W).to(device)
    torch.onnx.export(
        model,
        dummy,
        ONNX_PATH,
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
        opset_version=11,
    )


if __name__ == "__main__":
    train()
