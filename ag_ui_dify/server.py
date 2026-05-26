"""HTTP server endpoint for the AG-UI Dify adapter.

Single-port multi-agent server. Each Dify App is mounted at its own path:

  POST /company-paper    → Agent app (公司一页纸)
  POST /market-research  → Workflow app (市场调研)
  POST /meeting-bot      → Chat app (会议纪要)
  POST /code-convert     → Completion app (代码转换)

Configuration via environment variables:

  DIFY_AGENTS='{"agent-name": {"key": "app-xxx", "type": "agent"}, ...}'

Or for a single default agent:

  DIFY_API_KEY=app-xxx
  DIFY_APP_TYPE=agent
"""

import json
import os
from typing import AsyncGenerator, Dict, Optional

from ag_ui.core import BaseEvent, RunAgentInput
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


def create_dify_agent(config: dict) -> DifyAgent:
    """Create a DifyAgent from a raw config dict."""
    api_key = config.get("key", config.get("api_key", config.get("apiKey", "")))
    base_url = config.get("base_url", config.get(
        "baseUrl",
        os.environ.get("DIFY_BASE_URL", "https://api.dify.ai/v1"),
    ))
    app_type_raw = config.get("type", config.get("app_type", config.get("appType", "")))
    user = config.get("user", os.environ.get("DIFY_USER", "ag-ui-user"))
    timeout = float(config.get("timeout", os.environ.get("DIFY_TIMEOUT", "120.0")))

    if not api_key:
        raise ValueError(f"Agent config missing 'key' (Dify API key)")

    app_type: Optional[DifyAppType] = None
    if app_type_raw:
        try:
            app_type = DifyAppType(app_type_raw)
        except ValueError:
            pass

    return DifyAgent(DifyConfig(
        api_key=api_key,
        base_url=base_url,
        app_type=app_type,
        user=user,
        timeout=timeout,
    ))


def load_agents() -> Dict[str, DifyAgent]:
    """Load agent configurations from environment variables.

    Primary: DIFY_AGENTS JSON env var
      DIFY_AGENTS='{"agent-name":{"key":"app-xxx","type":"agent"},...}'

    Fallback: single default agent from DIFY_API_KEY
      DIFY_API_KEY=app-xxx DIFY_APP_TYPE=agent
    """
    agents: Dict[str, DifyAgent] = {}

    # Primary: DIFY_AGENTS JSON
    agents_json = os.environ.get("DIFY_AGENTS", "").strip()
    if agents_json:
        try:
            raw = json.loads(agents_json)
            for name, cfg in raw.items():
                agents[name] = create_dify_agent(cfg)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid DIFY_AGENTS JSON: {e}")

    # Fallback: single default agent
    if not agents:
        default_key = os.environ.get("DIFY_API_KEY", "")
        if default_key:
            agents["default"] = create_dify_agent({
                "key": default_key,
                "type": os.environ.get("DIFY_APP_TYPE", ""),
            })

    return agents


async def sse_stream(
    run_input: RunAgentInput,
    agent: DifyAgent,
) -> AsyncGenerator[str, None]:
    """Generate SSE-formatted AG-UI events from a DifyAgent run."""
    encoder = EventEncoder()
    async for event in agent.run(run_input):
        yield encoder.encode(event)


# ── Starlette / FastAPI ──────────────────────────────────────────

try:
    from starlette.requests import Request
    from starlette.responses import StreamingResponse, JSONResponse
    STARLETTE_AVAILABLE = True
except ImportError:
    STARLETTE_AVAILABLE = False


if STARLETTE_AVAILABLE:

    def _error_response(status: int, message: str):
        return JSONResponse({"error": message}, status_code=status)

    def _build_info_response() -> dict:
        """Build CopilotKit-compatible /info response."""
        agents = load_agents()
        agent_info: Dict[str, dict] = {}
        for name in agents:
            agent_info[name] = {
                "description": f"Dify agent: {name}",
                "capabilities": {
                    "streaming": True,
                    "tools": True,
                    "reasoning": True,
                    "state": True,
                },
            }
        return {
            "version": "1.0.0",
            "agents": agent_info,
            "mode": "sse",
        }

    async def info_endpoint(request: Request):
        """GET /info — CopilotKit agent discovery."""
        return JSONResponse(_build_info_response())

    def _make_agent_endpoint(agent: DifyAgent):
        """Create a POST endpoint function for a specific DifyAgent."""

        async def endpoint(request: Request) -> StreamingResponse:
            try:
                body = await request.json()
            except Exception:
                return _error_response(400, "Invalid JSON body")

            try:
                run_input = _parse_run_input(body)
            except Exception as e:
                return _error_response(400, f"Invalid RunAgentInput: {e}")

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

        return endpoint


def create_app():
    """Create a Starlette ASGI app with multi-agent path routing.

    Routes:
      POST /<agent-name>  – AG-UI RunAgentInput → SSE stream
      GET  /info           – CopilotKit agent discovery
      GET  /health         – Health check

    If no agents are configured, POST / serves a helpful error.
    """
    if not STARLETTE_AVAILABLE:
        raise ImportError(
            "Starlette is required for the HTTP server. "
            "Install with: pip install ag-ui-dify-adapter[server]"
        )

    from starlette.applications import Starlette
    from starlette.routing import Route

    agents = load_agents()

    routes = [
        Route("/info", info_endpoint, methods=["GET"]),
        Route("/health", _health_endpoint, methods=["GET"]),
    ]

    if agents:
        for name, agent in agents.items():
            routes.append(
                Route(f"/{name}", _make_agent_endpoint(agent), methods=["POST"])
            )
        # Also mount first agent at / for convenience if only one
        if len(agents) == 1:
            name = list(agents.keys())[0]
            routes.append(
                Route("/", _make_agent_endpoint(agents[name]), methods=["POST"])
            )
    else:
        # No agents configured → helpful error
        async def no_agents(request: Request):
            return JSONResponse({
                "error": "No Dify agents configured. "
                         "Set DIFY_AGENTS or DIFY_API_KEY environment variable."
            }, status_code=503)

        routes.append(Route("/", no_agents, methods=["POST"]))

    return Starlette(routes=routes)


def _health_endpoint(request=None):
    return JSONResponse({"status": "ok"})
