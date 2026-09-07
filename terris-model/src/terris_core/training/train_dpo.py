from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from datasets import load_dataset
from peft import LoraConfig
from transformers import AutoTokenizer, set_seed
from trl import DPOConfig, DPOTrainer


def main() -> None:
    parser = argparse.ArgumentParser(description="Preference optimization for Terris Core using expert-reviewed pairs.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-model", default=os.getenv("TERRIS_BASE_MODEL", "Qwen/Qwen3-8B"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--epochs", type=float, default=1.0)
    args = parser.parse_args()

    if not args.dataset.exists():
        raise FileNotFoundError(args.dataset)
    set_seed(args.seed)
    ds = load_dataset("json", data_files={"train": str(args.dataset)})["train"]
    required = {"prompt", "chosen", "rejected"}
    if not required.issubset(set(ds.column_names)):
        raise ValueError(f"Preference dataset requires columns: {sorted(required)}")

    tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=False)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    peft_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        bias="none",
        task_type="CAUSAL_LM",
    )
    training_args = DPOConfig(
        output_dir=str(args.output),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        learning_rate=5e-6,
        beta=0.1,
        logging_steps=5,
        save_strategy="epoch",
        report_to=[],
        seed=args.seed,
    )
    trainer = DPOTrainer(
        model=args.base_model,
        args=training_args,
        train_dataset=ds,
        processing_class=tokenizer,
        peft_config=peft_config,
    )
    trainer.train()
    args.output.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(args.output))
    tokenizer.save_pretrained(str(args.output))
    (args.output / "preference_training.json").write_text(json.dumps({
        "method": "DPO",
        "base_model": args.base_model,
        "records": len(ds),
        "seed": args.seed,
        "expert_review_required": True,
    }, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
