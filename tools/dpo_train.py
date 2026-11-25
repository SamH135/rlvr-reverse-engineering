"""DPO run B on a rented GPU: same recipe as notebooks/DirectPreferenceOptimization.ipynb.

Usage (on the pod): python dpo_train.py <adapter_dir> <pairs.jsonl> <out_adapter_dir> [--max-prompt-length N]
Policy and frozen ref are both the v5 SFT adapter (two 4-bit copies, as in run A).
"""
import argparse
import collections
import json

from datasets import Dataset
from trl import DPOConfig, DPOTrainer
from unsloth import FastLanguageModel

ap = argparse.ArgumentParser()
ap.add_argument("adapter")
ap.add_argument("pairs")
ap.add_argument("out")
ap.add_argument("--max-prompt-length", type=int, default=2048)
a = ap.parse_args()

model, tokenizer = FastLanguageModel.from_pretrained(a.adapter, max_seq_length=8192, load_in_4bit=True)
ref_model, _ = FastLanguageModel.from_pretrained(a.adapter, max_seq_length=8192, load_in_4bit=True)

with open(a.pairs, encoding="utf-8") as f:
    rows = [json.loads(line) for line in f]
ds = Dataset.from_list(rows)
print(len(ds), "pairs", collections.Counter(r["meta"].get("rejected_stop") for r in ds))
assert all(r["chosen"] != r["rejected"] and len(r["rejected"]) >= 1 for r in ds)
t = tokenizer.apply_chat_template(ds[0]["prompt"] + ds[0]["chosen"], tools=None, tokenize=False)
assert "<tool_call>" in t and "<tool_response>" in t, "template dropped tool turns"
over = [
    i for i, r in enumerate(rows)
    if len(tokenizer(tokenizer.apply_chat_template(r["prompt"], add_generation_prompt=True, tokenize=False), add_special_tokens=False)["input_ids"]) > a.max_prompt_length
]
assert not over, f"{len(over)} prompts exceed --max-prompt-length {a.max_prompt_length}: rows {over[:10]}"

trainer = DPOTrainer(model=model, ref_model=ref_model, args=DPOConfig(
    beta=0.1, max_length=8192, max_prompt_length=a.max_prompt_length,
    per_device_train_batch_size=1, gradient_accumulation_steps=8,
    num_train_epochs=1, learning_rate=2e-5, warmup_steps=1, logging_steps=1,
    optim="adamw_8bit", weight_decay=0.001, lr_scheduler_type="linear",
    seed=3407, report_to="none",
    output_dir=a.out + "_ckpt", save_strategy="epoch", save_total_limit=2),
    train_dataset=ds, processing_class=tokenizer)
trainer.train()
model.save_pretrained(a.out)
tokenizer.save_pretrained(a.out)
print("saved", a.out)
