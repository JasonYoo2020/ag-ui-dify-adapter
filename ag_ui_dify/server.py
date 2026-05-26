"""HTTP server endpoint for the AG-UI Dify adapter.

Provides a POST / endpoint that accepts RunAgentInput and streams
AG-UI SSE events, matching the ag_ui protocol.
"""

import json
from typing import AsyncGenerator

from ag_ui.core import BaseEvent, Event, RunAgentInput
from ag_ui.encoder import EventEncoder

from .agent import DifyAgent
from .types import DifyAppType, DifyConfig


def _parse_run_input(body: dict) -> RunAgentInput:
    """Parse a JSON dict into a RunAgentInput, accepting both camelCase and snake_case."""
    from ag_ui.core import Message
    from pydantic import TypeAdapter

    _message_adapter = TypeAdapter(Message)

    messages_raw = body.get("messages", [])
    messages = [_message_adapter.validate_python(m) for m in messages_raw]

    tools_raw = body.get("tools", [])
    tools = []
    for t in tools_raw:
        from ag_ui.core import Tool
        tools.append(Tool(**t) if isinstance(t, dict) else t)

    context_raw = body.get("context", [])
    context = []
    for c in context_raw:
        from ag_ui.core import Context
        context.append(Context(**c) if isinstance(c, dict) else c)

    return RunAgentInput(
        thread_id=body.get("threadId", body.get("thread_id", "")),
        run_id=body.get("runId", body.get("run_id", "")),
        state=body.get("state"),
        messages=messages,
        tools=tools,
        context=context,
        forwarded_props=body.get("forwardedProps", body.get("forwarded_props")),
    )


def create_dify_agent_from_forwarded_props(
    forwarded_props: dict,
) -> DifyAgent:
    """Extract DifyConfig from forwardedProps to create a DifyAgent."""
    api_key = forwarded_props.get("apiKey", forwarded_props.get("api_key", ""))
    base_url = forwarded_props.get("baseUrl", forwarded_props.get("base_url", "https://api.dify.ai/v1"))
    app_type_raw = forwarded_props.get("appType", forwarded_props.get("app_type"))
    user = forwarded_props.get("user", "ag-ui-user")
    timeout = forwarded_props.get("timeout", 120.0)

    app_type = None
    if app_type_raw:
        try:
            app_type = DifyAppType(app_type_raw)
        except ValueError:
            pass

    config = DifyConfig(
        api_key=api_key,
        base_url=base_url,
        app_type=app_type,
        user=user,
        timeout=timeout,
    )
    return DifyAgent(config)


async def sse_stream(
    run_input: RunAgentInput,
    agent: DifyAgent,
) -> AsyncGenerator[str, None]:
    """Generate SSE-formatted AG-UI events from a DifyAgent run."""
    encoder = EventEncoder()
    async for event in agent.run(run_input):
        yield encoder.encode(event)


# Starlette/FastAPI integration helpers
try:
    from starlette.requests import Request
    from starlette.responses import StreamingResponse
    STARLETTE_AVAILABLE = True
except ImportError:
    STARLETTE_AVAILABLE = False


if STARLETTE_AVAILABLE:

    def _error_response(status: int, message: str):
        from starlette.responses import JSONResponse
        return JSONResponse({"error": message}, status_code=status)

    async def agui_endpoint(request: Request) -> StreamingResponse:
        """Starlette/FastAPI endpoint that handles AG-UI RunAgentInput requests.

        Mount as::

            from starlette.applications import Starlette
            app = Starlette()
            app.add_route("/", agui_endpoint, methods=["POST"])
        """
        try:
            body = await request.json()
        except Exception:
            return _error_response(400, "Invalid JSON body")

        try:
            run_input = _parse_run_input(body)
        except Exception as e:
            return _error_response(400, f"Invalid RunAgentInput: {e}")

        forwarded_props = run_input.forwarded_props
        if not isinstance(forwarded_props, dict):
            return _error_response(
                400, "forwardedProps must contain Dify config: apiKey, baseUrl, appType"
            )

        try:
            agent = create_dify_agent_from_forwarded_props(forwarded_props)
        except Exception as e:
            return _error_response(400, f"Invalid Dify config: {e}")

        async def event_generator():
            encoder = EventEncoder()
            async for event in agent.run(run_input):
                yield encoder.encode(event)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )


def create_app():
    """Create a Starlette ASGI app with the AG-UI endpoint."""
    if not STARLETTE_AVAILABLE:
        raise ImportError(
            "Starlette is required for the HTTP server. "
            "Install with: pip install ag-ui-dify-adapter[server]"
        )

    from starlette.applications import Starlette
    from starlette.routing import Route

    app = Starlette(
        routes=[
            Route("/", agui_endpoint, methods=["POST"]),
            Route("/health", lambda _: _health_endpoint(), methods=["GET"]),
        ]
    )
    return app


def _health_endpoint():
    from starlette.responses import JSONResponse
    return JSONResponse({"status": "ok"})
