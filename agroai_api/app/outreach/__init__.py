"""AGRO-AI founder-led customer outreach machine."""

# Import the legacy module first so lifecycle and warm-buyer templates remain
# available, then install the Portal-first renderer before the router captures
# its render_email reference.
from . import templates as _legacy_templates
from .templates_v2 import render_email as _portal_first_render_email

_legacy_templates.render_email = _portal_first_render_email

from . import router as _router_module  # noqa: E402

_router_module.render_email = _portal_first_render_email
router = _router_module.router

__all__ = ["router"]
