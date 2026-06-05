"""
EduAI — Fine-tuning Skripti (RunPod / Colab üçün)
===================================================
Model: meta-llama/Llama-3.2-3B-Instruct
Metod: QLoRA (4-bit quantization + LoRA)
GPU tələbi: minimum 8GB VRAM (A100/A6000 tövsiyə edilir)

İstifadə (RunPod terminalında):
  pip install -r requirements_train.txt
  python train.py
"""

import json
import torch
from pathlib import Path
from datasets import Dataset
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    BitsAndBytesConfig,
    TrainingArguments,
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer

# ── Konfiqurasiya ──────────────────────────────────────────────────────────────

BASE_MODEL   = "meta-llama/Llama-3.2-3B-Instruct"
OUTPUT_DIR   = "./eduai-model-output"
TRAIN_FILE   = "../data/processed/train.jsonl"
VAL_FILE     = "../data/processed/val.jsonl"

LORA_CONFIG = LoraConfig(
    r=16,                        # LoRA rank
    lora_alpha=32,
    lora_dropout=0.05,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    bias="none",
    task_type="CAUSAL_LM",
)

TRAINING_ARGS = TrainingArguments(
    output_dir=OUTPUT_DIR,
    num_train_epochs=3,
    per_device_train_batch_size=2,
    per_device_eval_batch_size=2,
    gradient_accumulation_steps=8,
    learning_rate=2e-4,
    fp16=True,
    logging_steps=10,
    evaluation_strategy="steps",
    eval_steps=50,
    save_steps=100,
    save_total_limit=2,
    load_best_model_at_end=True,
    warmup_ratio=0.03,
    lr_scheduler_type="cosine",
    report_to="none",
)

# ── Məlumat yüklənməsi ─────────────────────────────────────────────────────────

def load_jsonl(path: str) -> Dataset:
    samples = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    return Dataset.from_list(samples)


def format_messages(sample: dict, tokenizer) -> dict:
    """Llama 3 chat formatına çevir"""
    text = tokenizer.apply_chat_template(
        sample["messages"],
        tokenize=False,
        add_generation_prompt=False,
    )
    return {"text": text}


# ── Əsas train prosesi ─────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("EduAI Model — Fine-tuning başlayır")
    print(f"Base model: {BASE_MODEL}")
    print("=" * 60)

    # 4-bit quantization (az VRAM üçün)
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )

    # Tokenizer
    print("\n[1/5] Tokenizer yüklənir...")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    # Model
    print("[2/5] Model yüklənir (4-bit)...")
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )
    model = prepare_model_for_kbit_training(model)
    model = get_peft_model(model, LORA_CONFIG)

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total     = sum(p.numel() for p in model.parameters())
    print(f"    Train ediləcək parametrlər: {trainable:,} / {total:,} ({100*trainable/total:.2f}%)")

    # Məlumat
    print("[3/5] Məlumat yüklənir...")
    train_ds = load_jsonl(TRAIN_FILE)
    val_ds   = load_jsonl(VAL_FILE)
    train_ds = train_ds.map(lambda x: format_messages(x, tokenizer))
    val_ds   = val_ds.map(lambda x: format_messages(x, tokenizer))
    print(f"    Train: {len(train_ds)} | Val: {len(val_ds)}")

    # Trainer
    print("[4/5] Trainer hazırlanır...")
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        dataset_text_field="text",
        max_seq_length=2048,
        args=TRAINING_ARGS,
    )

    # Train
    print("[5/5] Train başlayır...\n")
    trainer.train()

    # Saxla
    print("\n✅ Train tamamlandı. Model saxlanır...")
    trainer.save_model(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)
    print(f"Model saxlandı: {OUTPUT_DIR}")
    print("\nNövbəti addım: python quantize.py")


if __name__ == "__main__":
    main()
