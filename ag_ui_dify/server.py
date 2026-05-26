"""HTTP server endpoint for the AG-UI Dify adapter.

Provides POST / that accepts RunAgentInput and streams AG-UI SSE events,
plus GET /info for CopilotKit agent discovery and GET /health for probes.

Environment variables for standalone operation (no forwardedProps needed):
  DIFY_API_KEY   – Dify API key (required)
  DIFY_BASE_URL  – Dify base URL (default: https://api.dify.ai/v1)
  DIFY_APP_TYPE  – chat / agent / workflow / completion (default: auto-detect)

With env vars set, forwardedProps is optional. Explicit forwardedProps values
take precedence over env vars.
"""

import json
import os
from typing import AsyncGenerator, Optional

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


def _get_env_config() -> dict:
    """Read Dify config from environment variables."""
    return {
        "api_key": os.environ.get("DIFY_API_KEY", ""),
        "base_url": os.environ.get("DIFY_BASE_URL", "https://api.dify.ai/v1"),
        "app_type": os.environ.get("DIFY_APP_TYPE", ""),
        "user": os.environ.get("DIFY_USER", "ag-ui-user"),
        "timeout": float(os.environ.get("DIFY_TIMEOUT", "120.0")),
    }


def create_dify_agent_from_forwarded_props(
    forwarded_props: Optional[dict] = None,
) -> DifyAgent:
    """Extract DifyConfig from forwardedProps, with env-var fallback.

    forwardedProps takes precedence; env vars fill in missing fields.
    """
    fp = forwarded_props or {}
    env = _get_env_config()

    api_key = fp.get("apiKey", fp.get("api_key")) or env["api_key"]
    base_url = fp.get("baseUrl", fp.get("base_url")) or env["base_url"]
    app_type_raw = fp.get("appType", fp.get("app_type")) or env["app_type"]
    user = fp.get("user") or env["user"]
    timeout = fp.get("timeout") or env["timeout"]

    if not api_key:
        raise ValueError(
            "Dify API key is required. Set DIFY_API_KEY env var "
            "or pass apiKey in forwardedProps."
        )

    app_type: Optional[DifyAppType] = None
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
        timeout=float(timeout),
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
    from starlette.responses import StreamingResponse, JSONResponse
    STARLETTE_AVAILABLE = True
except ImportError:
    STARLETTE_AVAILABLE = False


if STARLETTE_AVAILABLE:

    def _error_response(status: int, message: str):
        return JSONResponse({"error": message}, status_code=status)

    def _build_info_response(request: Request) -> dict:
        """Build CopilotKit-compatible /info response."""
        env = _get_env_config()
        has_api_key = bool(env["api_key"])
        app_type = env["app_type"] or "auto"

        return {
            "version": "1.0.0",
            "agents": {
                "default": {
                    "description": f"Dify {app_type} agent via ag-ui-dify-adapter",
                    "capabilities": {
                        "streaming": True,
                        "tools": True,
                        "reasoning": True,
                        "state": True,
                    },
                }
            },
            "mode": "sse",
            "dify": {
                "baseUrl": env["base_url"],
                "appType": app_type,
                "configured": has_api_key,
            },
        }

    async def info_endpoint(request: Request):
        """GET /info — CopilotKit agent discovery endpoint."""
        return JSONResponse(_build_info_response(request))

    async def agui_endpoint(request: Request) -> StreamingResponse:
        """POST / — AG-UI RunAgentInput endpoint with SSE streaming.

        Accepts RunAgentInput JSON, translates to Dify API calls,
        and streams AG-UI events back.
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
            forwarded_props = {}

        # Merge env vars as fallback
        env = _get_env_config()
        if not forwarded_props.get("apiKey") and not forwarded_props.get("api_key"):
            if env["api_key"]:
                forwarded_props["apiKey"] = env["api_key"]
        if not forwarded_props.get("baseUrl") and not forwarded_props.get("base_url"):
            forwarded_props["baseUrl"] = env["base_url"]

        try:
            agent = create_dify_agent_from_forwarded_props(forwarded_props)
        except ValueError as e:
            return _error_response(400, str(e))
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
    """Create a Starlette ASGI app with AG-UI + CopilotKit-compatible routes.

    Routes:
      POST /         – AG-UI RunAgentInput → SSE stream
      GET  /info     – CopilotKit agent discovery
      GET  /health   – Health check probe
    """
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
            Route("/info", info_endpoint, methods=["GET"]),
            Route("/health", _health_endpoint, methods=["GET"]),
        ]
    )
    return app


def _health_endpoint(request=None):
    return JSONResponse({"status": "ok"})
