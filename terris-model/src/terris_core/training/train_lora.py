from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from datasets import load_dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    Trainer,
    TrainingArguments,
    set_seed,
)


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fallback_render(messages: list[dict]) -> str:
    return "\n\n".join(f"{message['role'].upper()}: {message['content']}" for message in messages)


def encode_assistant_only(tokenizer, messages: list[dict], max_length: int) -> dict:
    """Tokenize a chat while computing loss only on assistant response spans.

    Terris is post-trained to learn the desired agricultural answer/tool behavior,
    not to spend gradient reproducing system policy or farmer input.
    """
    if not getattr(tokenizer, "chat_template", None):
        text = _fallback_render(messages)
        encoded = tokenizer(text, truncation=True, max_length=max_length, padding=False)
        # Conservative fallback for tokenizers without a chat template. A compatible
        # production base model should have a chat template; fail later if no assistant
        # tokens survive.
        encoded["labels"] = encoded["input_ids"].copy()
        return encoded

    full_ids = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=False,
    )[:max_length]
    labels = [-100] * len(full_ids)

    for index, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue

        prior = messages[:index]
        through_response = messages[: index + 1]

        prompt_ids = tokenizer.apply_chat_template(
            prior,
            tokenize=True,
            add_generation_prompt=True,
        )
        response_ids = tokenizer.apply_chat_template(
            through_response,
            tokenize=True,
            add_generation_prompt=False,
        )

        start = min(len(prompt_ids), len(full_ids))
        end = min(len(response_ids), len(full_ids))
        if end > start:
            labels[start:end] = full_ids[start:end]

    if not any(label != -100 for label in labels):
        raise ValueError("No assistant response tokens remain after tokenization/truncation.")

    return {
        "input_ids": full_ids,
        "attention_mask": [1] * len(full_ids),
        "labels": labels,
    }


@dataclass
class CausalMaskedCollator:
    tokenizer: Any
    label_pad_token_id: int = -100

    def __call__(self, features: list[dict]) -> dict[str, torch.Tensor]:
        max_len = max(len(feature["input_ids"]) for feature in features)
        pad_id = self.tokenizer.pad_token_id
        if pad_id is None:
            raise ValueError("Tokenizer requires a pad token for batching.")

        input_ids = []
        attention_mask = []
        labels = []

        for feature in features:
            pad = max_len - len(feature["input_ids"])
            input_ids.append(feature["input_ids"] + [pad_id] * pad)
            attention_mask.append(feature.get("attention_mask", [1] * len(feature["input_ids"])) + [0] * pad)
            labels.append(feature["labels"] + [self.label_pad_token_id] * pad)

        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "attention_mask": torch.tensor(attention_mask, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
        }


def build_quantization_config(cfg: dict):
    if not cfg.get("qlora_4bit", True):
        return None
    if not torch.cuda.is_available():
        raise RuntimeError("QLoRA 4-bit training requires a CUDA GPU. Set qlora_4bit=false for CPU development.")
    compute_dtype = torch.bfloat16 if cfg.get("bf16", True) else torch.float16
    return BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=compute_dtype,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="LoRA/QLoRA supervised post-training for Terris Core.")
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
    tokenizer.padding_side = "right"

    quantization_config = build_quantization_config(cfg)
    dtype = torch.bfloat16 if cfg.get("bf16", True) and torch.cuda.is_available() else torch.float32

    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        torch_dtype=None if quantization_config else dtype,
        quantization_config=quantization_config,
        trust_remote_code=False,
    )
    model.config.use_cache = False

    if quantization_config is not None:
        model = prepare_model_for_kbit_training(
            model,
            use_gradient_checkpointing=bool(cfg.get("gradient_checkpointing", True)),
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

    if quantization_config is None and cfg.get("gradient_checkpointing", True):
        model.enable_input_require_grads()
        model.gradient_checkpointing_enable()

    trainable, total = model.get_nb_trainable_parameters()
    if trainable <= 0:
        raise RuntimeError("Terris Core training has zero trainable parameters.")

    dataset = load_dataset("json", data_files={"train": str(train_file)})["train"]
    max_length = int(cfg.get("max_length", 4096))

    def tokenize(example):
        return encode_assistant_only(tokenizer, example["messages"], max_length)

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
        seed=int(cfg.get("seed", 42)),
        data_seed=int(cfg.get("seed", 42)),
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized,
        data_collator=CausalMaskedCollator(tokenizer=tokenizer),
    )
    train_result = trainer.train()

    output_dir.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))

    metrics = {
        key: float(value) if isinstance(value, (int, float)) else value
        for key, value in train_result.metrics.items()
    }
    run_metadata = {
        "run_name": cfg["run_name"],
        "base_model": base_model,
        "qlora_4bit": bool(quantization_config is not None),
        "assistant_only_loss": True,
        "trainable_parameters": trainable,
        "total_parameters": total,
        "trainable_fraction": trainable / total if total else 0,
        "metrics": metrics,
    }
    (output_dir / "training_metrics.json").write_text(
        json.dumps(run_metadata, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "base_model.txt").write_text(base_model + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "output_dir": str(output_dir), **run_metadata}))


if __name__ == "__main__":
    main()
