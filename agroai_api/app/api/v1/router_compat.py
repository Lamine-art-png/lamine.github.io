from __future__ import annotations

from typing import Any

from fastapi.routing import APIRoute
from starlette.routing import BaseRoute


def materialize_included_routes(router: Any) -> None:
    """Expand FastAPI deferred router includes for current route contracts.

    The production tests and older runtime contract inspect concrete route
    paths on ``app.routes`` and router ``.routes``. FastAPI 0.123 stores
    includes as private ``_IncludedRouter`` wrappers, so materialize them after
    all local composition hooks have run.
    """
    try:
        from fastapi.routing import _IncludedRouter
    except Exception:  # pragma: no cover - older FastAPI already flattens.
        return

    routes = getattr(router, "routes", None)
    if routes is None:
        return

    materialized: list[BaseRoute] = []
    changed = False
    for route in list(routes):
        if isinstance(route, _IncludedRouter):
            changed = True
            for context in route.effective_route_contexts():
                materialized.append(_route_from_context(context))
        else:
            materialized.append(route)
    if changed:
        routes[:] = materialized


def _route_from_context(context: Any) -> BaseRoute:
    original = context.original_route
    starlette_route = getattr(context, "starlette_route", None)
    if not isinstance(original, APIRoute):
        return starlette_route or original

    route = APIRoute(
        context.path,
        context.endpoint,
        response_model=context.response_model,
        status_code=context.status_code,
        tags=context.tags,
        dependencies=context.dependencies,
        summary=context.summary,
        description=context.description,
        response_description=context.response_description,
        responses=context.responses,
        deprecated=context.deprecated,
        name=context.name,
        methods=context.methods,
        operation_id=context.operation_id,
        response_model_include=context.response_model_include,
        response_model_exclude=context.response_model_exclude,
        response_model_by_alias=context.response_model_by_alias,
        response_model_exclude_unset=context.response_model_exclude_unset,
        response_model_exclude_defaults=context.response_model_exclude_defaults,
        response_model_exclude_none=context.response_model_exclude_none,
        include_in_schema=context.include_in_schema,
        response_class=context.response_class,
        dependency_overrides_provider=context.dependency_overrides_provider,
        callbacks=context.callbacks,
        openapi_extra=context.openapi_extra,
        generate_unique_id_function=context.generate_unique_id_function,
        strict_content_type=context.strict_content_type,
    )
    for key, value in vars(original).items():
        if key.startswith("_agroai_"):
            setattr(route, key, value)
    return route
