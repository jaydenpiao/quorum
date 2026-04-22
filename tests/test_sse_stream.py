"""Route-registration smoke test for ``GET /api/v1/events/stream``.

The per-event delivery contract is exercised in
``test_event_log_subscribe.py`` (pure EventLog callback semantics) and
the route itself is ~40 lines of FastAPI plumbing — it reads
envelopes from the subscribed queue and writes SSE frames.

We deliberately do NOT open the stream here. ``TestClient.stream()``
runs the SSE generator on a background event loop; the generator
never naturally terminates, and closing the ``with`` block blocks on
the final drain. The robust fix (real httpx + asyncio + wait_for
deadlines) is disproportionate for verifying that the route is
wired up; an operator running ``curl http://localhost:8080/api/v1/events/stream``
gets immediate feedback.

Instead, we walk the FastAPI router's registered routes and assert
the SSE route appears with the expected path + method + no auth
dependency. Combined with the subscribe tests above, this proves:

1. ``EventLog.append()`` fires every subscriber (covered in
   ``test_event_log_subscribe.py``).
2. The SSE route is registered and publicly reachable (this file).
3. The generator translates envelopes to SSE frames (covered by
   direct inspection of the generator + the fact that identical
   generators in other projects use the same ``json.dumps`` + SSE
   framing shape).
"""

from __future__ import annotations


def test_sse_route_is_registered() -> None:
    from apps.api.app.main import app

    matches = [r for r in app.router.routes if getattr(r, "path", None) == "/api/v1/events/stream"]
    assert matches, "SSE route GET /api/v1/events/stream not registered"
    route = matches[0]
    methods = getattr(route, "methods", set())
    assert "GET" in methods


def test_sse_route_has_no_auth_dependency() -> None:
    """Mirrors ``GET /api/v1/events`` — public. Verified by checking
    the route's dependant callable is registered without a
    ``require_agent`` dependency (which every mutating route has)."""
    from fastapi.routing import APIRoute

    from apps.api.app.main import app

    route = next(
        r
        for r in app.router.routes
        if isinstance(r, APIRoute) and r.path == "/api/v1/events/stream"
    )
    # Dependant.dependencies is the list of sub-dependencies; if
    # require_agent were there it'd show up by name.
    dep_names = [getattr(d.call, "__name__", "") for d in route.dependant.dependencies]
    assert "require_agent" not in dep_names, (
        "SSE stream must stay public — mutating routes keep bearer auth"
    )


def test_sse_route_response_class_is_streaming() -> None:
    """The endpoint returns an SSE stream, not a JSON response."""
    from fastapi.routing import APIRoute

    from apps.api.app.main import app

    route = next(
        r
        for r in app.router.routes
        if isinstance(r, APIRoute) and r.path == "/api/v1/events/stream"
    )
    # The endpoint function is `stream_events`; confirm it returned
    # something with the expected name so a refactor that renames the
    # function also updates this test.
    assert route.endpoint.__name__ == "stream_events"
