"""
EduAI — Model Quantizasiya Skripti
====================================
Train olunmuş modeli llama.cpp üçün .gguf formatına çevirir.
4GB VRAM-da işləmək üçün Q4_K_M quantizasiyası.

İstifadə (RunPod terminalında, train.py-dan sonra):
  python quantize.py

Nəticə: eduai-model-q4.gguf (öz serverinizə kopyalayın)
"""

import os
import subprocess
from pathlib import Path

MODEL_DIR    = "./eduai-model-output"
OUTPUT_FILE  = "./eduai-model-q4.gguf"
LLAMA_CPP    = "./llama.cpp"          # llama.cpp repo yolu


def check_llama_cpp():
    if not Path(LLAMA_CPP).exists():
        print("llama.cpp tapılmadı. Yüklənir...")
        subprocess.run([
            "git", "clone",
            "https://github.com/ggerganov/llama.cpp",
            LLAMA_CPP
        ], check=True)
        subprocess.run(["make", "-C", LLAMA_CPP, "-j4"], check=True)
        print("llama.cpp hazır.")


def merge_lora():
    """LoRA adapter-i base model ilə birləşdir"""
    print("[1/3] LoRA adapter birləşdirilir...")
    merge_script = f"""
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

base_model = "meta-llama/Llama-3.2-3B-Instruct"
adapter_path = "{MODEL_DIR}"
output_path = "./eduai-model-merged"

print("  Base model yüklənir...")
model = AutoModelForCausalLM.from_pretrained(
    base_model, torch_dtype=torch.float16, device_map="cpu"
)
print("  LoRA adapter birləşdirilir...")
model = PeftModel.from_pretrained(model, adapter_path)
model = model.merge_and_unload()

print("  Birləşdirilmiş model saxlanır...")
model.save_pretrained(output_path)
tokenizer = AutoTokenizer.from_pretrained(adapter_path)
tokenizer.save_pretrained(output_path)
print("  Tamamlandı: ./eduai-model-merged")
"""
    with open("_merge_tmp.py", "w") as f:
        f.write(merge_script)
    subprocess.run(["python", "_merge_tmp.py"], check=True)
    os.remove("_merge_tmp.py")


def convert_to_gguf():
    """Birləşdirilmiş modeli .gguf formatına çevir"""
    print("[2/3] .gguf formatına çevrilir...")
    subprocess.run([
        "python", f"{LLAMA_CPP}/convert_hf_to_gguf.py",
        "./eduai-model-merged",
        "--outfile", "./eduai-model-f16.gguf",
        "--outtype", "f16",
    ], check=True)


def quantize_q4():
    """Q4_K_M quantizasiyası — 4GB VRAM üçün optimal"""
    print("[3/3] Q4_K_M quantizasiyası...")
    subprocess.run([
        f"{LLAMA_CPP}/llama-quantize",
        "./eduai-model-f16.gguf",
        OUTPUT_FILE,
        "Q4_K_M",
    ], check=True)
    size = Path(OUTPUT_FILE).stat().st_size / (1024**3)
    print(f"\n✅ Hazır: {OUTPUT_FILE} ({size:.1f} GB)")
    print("Bu faylı öz serverinizə kopyalayın.")


def main():
    print("=" * 60)
    print("EduAI Model — Quantizasiya")
    print("=" * 60)
    check_llama_cpp()
    merge_lora()
    convert_to_gguf()
    quantize_q4()
    print("\nNövbəti addım:")
    print("  1. eduai-model-q4.gguf faylını öz serverinizə kopyalayın")
    print("  2. cd ../serve && python server.py")


if __name__ == "__main__":
    main()
