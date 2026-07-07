import json
import re

from app.services.ai_gateway import AIGatewayResult
from app.services.model_router import ModelRouter
from app.services.ui_translation_fallback import translate_ui_mapping

_ORIGINAL = ModelRouter.run


async def _run(self, **kwargs):
    result, selection = await _ORIGINAL(self, **kwargs)
    if kwargs.get("task") != "ui_translation" or (result.status == "ok" and result.content.strip()):
        return result, selection
    messages = kwargs.get("messages") or []
    try:
        source = json.loads(str(messages[-1].get("content") or ""))
        system = "\n".join(str(x.get("content") or "") for x in messages if x.get("role") == "system")
        match = re.search(r"\(([A-Za-z0-9_-]+)\)", system)
        locale = match.group(1) if match else ""
        fallback = await translate_ui_mapping(locale, source)
    except Exception as exc:
        result.error = f"{result.error or 'primary unavailable'}; fallback={exc}"
        return result, selection
    return AIGatewayResult(
        status="ok",
        content=json.dumps(fallback.catalog, ensure_ascii=False),
        provider=fallback.provider,
        model=fallback.model,
    ), selection


def install_ui_translation_patch():
    if not getattr(ModelRouter, "_ui_translation_patch", False):
        ModelRouter.run = _run
        ModelRouter._ui_translation_patch = True
