"""AGRO-AI founder-led customer outreach machine."""

# The production API router uses the Portal-first renderer for cold outreach.
# The legacy templates module remains unchanged so lifecycle and warm-buyer
# renderers keep their established behavior and regression coverage.
from .templates_v2 import render_email as _portal_first_render_email
from . import router as _router_module  # noqa: E402

_router_module.render_email = _portal_first_render_email
router = _router_module.router

__all__ = ["router"]
