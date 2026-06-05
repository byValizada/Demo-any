"""
EduAI — Məlumat Hazırlama Skripti
===================================
Xam JSONL fayllarını train/validation dəstlərinə bölür.
İstifadə: python prepare_data.py
"""

import json
import random
import os
from pathlib import Path

RAW_DIR       = Path(__file__).parent.parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
PROCESSED_DIR.mkdir(exist_ok=True)

TRAIN_RATIO = 0.9   # 90% train, 10% validation


def load_all_data() -> list[dict]:
    """data/raw/ qovluğundakı bütün .jsonl fayllarını oxu"""
    all_samples = []
    for fpath in RAW_DIR.glob("*.jsonl"):
        with open(fpath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    sample = json.loads(line)
                    all_samples.append(sample)
                except json.JSONDecodeError as e:
                    print(f"[XƏTA] {fpath.name} — {e}")
    return all_samples


def validate_sample(sample: dict) -> bool:
    """Nümunənin düzgün formatda olduğunu yoxla"""
    if "messages" not in sample:
        return False
    msgs = sample["messages"]
    if len(msgs) < 2:
        return False
    roles = [m.get("role") for m in msgs]
    if "user" not in roles or "assistant" not in roles:
        return False
    return True


def split_and_save(samples: list[dict]):
    """Train/validation bölgüsü et və saxla"""
    random.shuffle(samples)
    split_idx = int(len(samples) * TRAIN_RATIO)
    train_data = samples[:split_idx]
    val_data   = samples[split_idx:]

    for name, data in [("train.jsonl", train_data), ("val.jsonl", val_data)]:
        out_path = PROCESSED_DIR / name
        with open(out_path, "w", encoding="utf-8") as f:
            for sample in data:
                f.write(json.dumps(sample, ensure_ascii=False) + "\n")
        print(f"[OK] {name} — {len(data)} nümunə")


def main():
    print("=" * 50)
    print("EduAI — Məlumat Hazırlama")
    print("=" * 50)

    samples = load_all_data()
    print(f"\nCəmi yükləndi: {len(samples)} nümunə")

    valid = [s for s in samples if validate_sample(s)]
    invalid = len(samples) - len(valid)
    if invalid:
        print(f"[XƏBƏRDARLIQ] {invalid} nümunə etibarsız formatda — atlandı")

    print(f"Etibarlı nümunə: {len(valid)}")
    print(f"Train: {int(len(valid) * TRAIN_RATIO)} | Val: {len(valid) - int(len(valid) * TRAIN_RATIO)}")

    split_and_save(valid)
    print("\n✅ Məlumat hazırdır: data/processed/")


if __name__ == "__main__":
    main()
