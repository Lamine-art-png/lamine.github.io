from __future__ import annotations

import json
import os
import time
import uuid
from functools import lru_cache

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

from terris_core.serve.contracts import AgricultureRequest, AgricultureResponse

MODEL_PATH = os.getenv("TERRIS_MODEL_PATH", "artifacts/models/terris-core-v0")
BASE_MODEL = os.getenv("TERRIS_BASE_MODEL", "Qwen/Qwen3-8B")
MODEL_NAME = os.getenv("TERRIS_MODEL_NAME", "terris-core-v0")
PORT = int(os.getenv("PORT", "8008"))

SYSTEM_POLICY = """You are Terris Core, AGRO-AI's agriculture-native reasoning model.
Use field facts exactly as labeled. Never turn estimated, reported, inferred, or unknown data into measured facts.
Never claim that an action was executed, verified, legally compliant, or successful unless supplied evidence establishes it.
When numeric agronomy depends on deterministic calculations, weather, sensors, equipment, satellite data, or regulatory sources, request or use the appropriate tool instead of inventing a value.
If important context is missing, state what is missing and lower confidence. Prefer safe, reversible next actions.
Do not promise yields, savings, disease outcomes, or regulatory approval."""


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = MODEL_NAME
    messages: list[Message] = Field(min_length=1)
    temperature: float = 0.1
    max_tokens: int = Field(default=900, ge=1, le=4096)


class ModelBundle:
    def __init__(self):
        adapter_exists = os.path.exists(os.path.join(MODEL_PATH, "adapter_config.json"))
        tokenizer_source = MODEL_PATH if adapter_exists else BASE_MODEL
        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_source, trust_remote_code=False)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        base = AutoModelForCausalLM.from_pretrained(BASE_MODEL, torch_dtype=dtype, device_map="auto" if torch.cuda.is_available() else None, trust_remote_code=False)
        self.model = PeftModel.from_pretrained(base, MODEL_PATH) if adapter_exists else base
        self.model.eval()
        self.adapter_loaded = adapter_exists

    def generate(self, messages: list[dict], temperature: float, max_tokens: int) -> str:
        conversation = [{"role": "system", "content": SYSTEM_POLICY}, *messages]
        if getattr(self.tokenizer, "chat_template", None):
            prompt = self.tokenizer.apply_chat_template(conversation, tokenize=False, add_generation_prompt=True)
        else:
            prompt = "\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in conversation) + "\n\nASSISTANT:"
        encoded = self.tokenizer(prompt, return_tensors="pt")
        if torch.cuda.is_available():
            encoded = {key: value.to(self.model.device) for key, value in encoded.items()}
        do_sample = temperature > 0
        with torch.no_grad():
            output = self.model.generate(**encoded, max_new_tokens=max_tokens, do_sample=do_sample, temperature=max(temperature, 1e-5) if do_sample else None, pad_token_id=self.tokenizer.pad_token_id, eos_token_id=self.tokenizer.eos_token_id)
        generated = output[0][encoded["input_ids"].shape[-1]:]
        return self.tokenizer.decode(generated, skip_special_tokens=True).strip()


@lru_cache(maxsize=1)
def get_bundle() -> ModelBundle:
    return ModelBundle()


app = FastAPI(title="Terris Core Inference", version="0.2.0")


@app.get("/health")
def health():
    return {"ok": True, "service": "terris-core", "model": MODEL_NAME, "model_path": MODEL_PATH, "base_model": BASE_MODEL, "loaded": get_bundle.cache_info().currsize > 0}


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": MODEL_NAME, "object": "model", "owned_by": "agro-ai", "adapter_loaded": get_bundle().adapter_loaded}]}


def agriculture_operation(request: AgricultureRequest) -> AgricultureResponse:
    facts = [fact.model_dump() for fact in request.facts]
    context = {
        "operation": request.operation,
        "field_id": request.field_id,
        "crop_cycle_id": request.crop_cycle_id,
        "language": request.language,
        "facts": facts,
        "available_tools": request.available_tools,
        "evidence": request.evidence,
    }
    instruction = (
        f"Perform Terris operation '{request.operation}'. Farmer/operator question: {request.question}\n"
        f"Structured field context: {json.dumps(context, ensure_ascii=False, sort_keys=True)}\n"
        "If a required external or deterministic fact is unavailable, name the tool needed rather than fabricating the value."
    )
    answer = get_bundle().generate([{"role": "user", "content": instruction}], temperature=0.0, max_tokens=request.max_tokens)
    requested_tools = [tool for tool in request.available_tools if tool.lower() in answer.lower()]
    return AgricultureResponse(operation=request.operation, model=MODEL_NAME, answer=answer, field_id=request.field_id, requested_tools=requested_tools)


@app.post("/v1/reason", response_model=AgricultureResponse)
def reason(request: AgricultureRequest):
    request.operation = "reason"
    return agriculture_operation(request)


@app.post("/v1/recommend", response_model=AgricultureResponse)
def recommend(request: AgricultureRequest):
    request.operation = "recommend"
    return agriculture_operation(request)


@app.post("/v1/explain", response_model=AgricultureResponse)
def explain(request: AgricultureRequest):
    request.operation = "explain"
    return agriculture_operation(request)


@app.post("/v1/verify", response_model=AgricultureResponse)
def verify(request: AgricultureRequest):
    request.operation = "verify"
    return agriculture_operation(request)


@app.post("/v1/chat/completions")
def chat(request: ChatRequest):
    try:
        started = time.time()
        bundle = get_bundle()
        answer = bundle.generate([message.model_dump() for message in request.messages], temperature=request.temperature, max_tokens=request.max_tokens)
        return {"id": "terris-" + uuid.uuid4().hex, "object": "chat.completion", "created": int(started), "model": MODEL_NAME, "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}], "usage": {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}}
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Terris Core inference failed") from exc


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("terris_core.serve.app:app", host="0.0.0.0", port=PORT)
