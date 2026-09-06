from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import torch
from datasets import load_dataset
from peft import LoraConfig, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    DataCollatorForLanguageModeling,
    Trainer,
    TrainingArguments,
    set_seed,
)


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def render_messages(tokenizer, example: dict) -> str:
    messages = example["messages"]
    if getattr(tokenizer, "chat_template", None):
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
    chunks = []
    for message in messages:
        chunks.append(f"{message['role'].upper()}: {message['content']}")
    return "\n\n".join(chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description="LoRA supervised post-training for Terris Core.")
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    cfg = load_config(args.config)

    set_seed(int(cfg.get("seed", 42)))
    base_model = os.getenv("TERRIS_BASE_MODEL", cfg["base_model"])
    train_file = Path(cfg["train_file"])
    output_dir = Path(cfg["output_dir"])

    if not train_file.exists():
        raise FileNotFoundError(
            f"{train_file} does not exist. Run terris_core.data.prepare before training."
        )

    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=False)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    dtype = torch.bfloat16 if cfg.get("bf16", True) and torch.cuda.is_available() else torch.float32
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        torch_dtype=dtype,
        device_map="auto" if torch.cuda.is_available() else None,
        trust_remote_code=False,
    )

    lora_cfg = cfg["lora"]
    peft_config = LoraConfig(
        r=int(lora_cfg["r"]),
        lora_alpha=int(lora_cfg["alpha"]),
        lora_dropout=float(lora_cfg["dropout"]),
        target_modules=list(lora_cfg["target_modules"]),
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, peft_config)
    if cfg.get("gradient_checkpointing", True):
        model.enable_input_require_grads()
        model.gradient_checkpointing_enable()

    dataset = load_dataset("json", data_files={"train": str(train_file)})["train"]
    max_length = int(cfg.get("max_length", 4096))

    def tokenize(example):
        text = render_messages(tokenizer, example)
        encoded = tokenizer(
            text,
            truncation=True,
            max_length=max_length,
            padding=False,
        )
        encoded["labels"] = encoded["input_ids"].copy()
        return encoded

    tokenized = dataset.map(tokenize, remove_columns=dataset.column_names)

    training_args = TrainingArguments(
        output_dir=str(output_dir),
        run_name=cfg["run_name"],
        num_train_epochs=float(cfg.get("epochs", 2)),
        learning_rate=float(cfg.get("learning_rate", 2e-4)),
        warmup_ratio=float(cfg.get("warmup_ratio", 0.05)),
        weight_decay=float(cfg.get("weight_decay", 0.01)),
        per_device_train_batch_size=int(cfg.get("per_device_train_batch_size", 1)),
        gradient_accumulation_steps=int(cfg.get("gradient_accumulation_steps", 8)),
        logging_steps=int(cfg.get("logging_steps", 5)),
        save_steps=int(cfg.get("save_steps", 100)),
        save_total_limit=3,
        bf16=bool(cfg.get("bf16", True) and torch.cuda.is_available()),
        fp16=bool(not cfg.get("bf16", True) and torch.cuda.is_available()),
        report_to=[],
        remove_unused_columns=False,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized,
        data_collator=DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False),
    )
    train_result = trainer.train()

    output_dir.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))
    metrics = {key: float(value) if isinstance(value, (int, float)) else value for key, value in train_result.metrics.items()}
    (output_dir / "training_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    (output_dir / "base_model.txt").write_text(base_model + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "output_dir": str(output_dir), "base_model": base_model, "metrics": metrics}))


if __name__ == "__main__":
    main()
