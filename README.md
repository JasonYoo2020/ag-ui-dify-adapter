# ag-ui-dify-adapter

AG-UI protocol adapter for Dify — translates [Dify](https://dify.ai) API responses to [AG-UI](https://ag-ui.com) streaming events, enabling Dify-powered AI agents to integrate with any AG-UI-compatible frontend.

## Features

- **All 4 Dify app types**: Chat, Agent, Workflow, Completion
- **24+ AG-UI event types**: TEXT_MESSAGE, TOOL_CALL, TOOL_CALL_RESULT, REASONING, STATE_SNAPSHOT, MESSAGES_SNAPSHOT, STEP, CUSTOM, RAW, RUN
- **Tool call lifecycle**: `TOOL_CALL_START` → `ARGS` → `END` → `RESULT` for Agent ReAct loops
- **Reasoning events**: `<think>` tag streaming detection → `REASONING_START/MESSAGE_START/CONTENT/MESSAGE_END/END`
- **Snapshots**: `MESSAGES_SNAPSHOT` + `STATE_SNAPSHOT` emitted at start of every run
- **Streaming**: Real-time text streaming with `<think>` block separation
- **Multi-turn conversation**: `thread_id` ↔ `conversation_id` tracking
- **State & context**: AG-UI state/context → Dify input variables
- **Single-port multi-agent**: One server, multiple Dify apps routed by path
- **RAW passthrough**: Unrecognized Dify events forwarded as `RAW`, never dropped
- **Async**: Full async support with `httpx`

## Installation

```bash
pip install ag-ui-dify-adapter
```

For the HTTP server:

```bash
pip install ag-ui-dify-adapter[server]
```

## Quick Start

### Library

```python
import asyncio
from ag_ui_dify import DifyAgent, DifyConfig, DifyAppType
from ag_ui.core import RunAgentInput, UserMessage

async def main():
    agent = DifyAgent(DifyConfig(
        api_key="app-xxx",
        base_url="https://api.dify.ai/v1",
        app_type=DifyAppType.AGENT,
    ))

    input = RunAgentInput(
        thread_id="thread-1",
        run_id="run-1",
        state=None,
        messages=[UserMessage(id="u1", role="user", content="Hello!")],
        tools=[], context=[], forwarded_props={},
    )

    async for event in agent.run(input):
        print(event.model_dump_json(by_alias=True))

asyncio.run(main())
```

### HTTP Server

```bash
# Single agent
DIFY_API_KEY=app-xxx DIFY_APP_TYPE=agent \
  uvicorn ag_ui_dify:create_app --port 8080

# Multi-agent (single port, routed by path)
DIFY_AGENTS='{
  "agent-a": {"key": "app-xxx", "type": "agent"},
  "wf-b":    {"key": "app-yyy", "type": "workflow"}
}' \
  uvicorn ag_ui_dify:create_app --port 8080
```

API keys are configured server-side via environment variables — never exposed to clients.

```bash
# Endpoints
curl -X POST http://localhost:8080/agent-a \
  -H "Content-Type: application/json" \
  -d '{"threadId":"t1","runId":"r1","messages":[{"id":"u1","role":"user","content":"Hello"}],"tools":[],"context":[]}'

curl http://localhost:8080/health   # → {"status":"ok"}
curl http://localhost:8080/info     # → agent discovery
```

## Dify → AG-UI Event Mapping

### Agent App

| Dify SSE Event | AG-UI Event(s) |
|---|---|
| `agent_thought` (with thought) | `STEP_STARTED` + `CUSTOM` (thought) |
| `agent_thought` (with tool) | `TOOL_CALL_START` + `TOOL_CALL_ARGS` + `TOOL_CALL_END` |
| `agent_thought` (with observation) | `TOOL_CALL_RESULT` |
| `agent_message` (first) | `TEXT_MESSAGE_START` |
| `agent_message` | `TEXT_MESSAGE_CONTENT` (with `<think>` → `REASONING`) |
| `message_replace` | `CUSTOM` |
| `message_file` | `CUSTOM` |
| `message_end` | `TEXT_MESSAGE_END` + `RUN_FINISHED` |

### Workflow App

| Dify SSE Event | AG-UI Event(s) |
|---|---|
| `workflow_started` | `RUN_STARTED` + `TEXT_MESSAGE_START` |
| `node_started` / `node_retry` | `STEP_STARTED` |
| `node_finished` | `STEP_FINISHED` |
| `agent_log` | `STEP_STARTED` / `STEP_FINISHED` |
| `iteration_started/completed` | `STEP_STARTED` / `STEP_FINISHED` |
| `loop_started/completed` | `STEP_STARTED` / `STEP_FINISHED` |
| `text_chunk` | `TEXT_MESSAGE_CONTENT` (with `<think>` → `REASONING`) |
| `text_replace` | `CUSTOM` |
| `workflow_paused` | `CUSTOM` + `RUN_FINISHED` |
| `human_input_*` | `CUSTOM` |
| `workflow_finished` | `TEXT_MESSAGE_END` + `RUN_FINISHED` |

### Chat / Completion App

| Dify SSE Event | AG-UI Event(s) |
|---|---|
| `message` (first) | `TEXT_MESSAGE_START` |
| `message` | `TEXT_MESSAGE_CONTENT` (with `<think>` → `REASONING`) |
| `message_replace` | `CUSTOM` |
| `message_file` | `CUSTOM` |
| `tts_message` / `tts_message_end` | `CUSTOM` |
| `message_end` | `TEXT_MESSAGE_END` + `RUN_FINISHED` |

**All app types**: `MESSAGES_SNAPSHOT` + `STATE_SNAPSHOT` at start, `RUN_STARTED`, `RUN_ERROR` on error, `ping` ignored, unknown events → `RAW`.

## API Reference

### DifyAgent

```python
agent = DifyAgent(DifyConfig(
    api_key="app-xxx",          # Required: Dify API key
    base_url="...",             # Default: https://api.dify.ai/v1
    app_type=DifyAppType.AGENT, # Auto-detected if omitted
    user="ag-ui-user",          # Default user identifier
    timeout=120.0,              # HTTP timeout in seconds
))
async for event in agent.run(run_input):
    ...
```

### HTTP Server

```python
from ag_ui_dify import create_app, load_agents
import uvicorn

# Programmatic
agents = load_agents()  # reads DIFY_AGENTS / DIFY_API_KEY from env
app = create_app()      # Starlette app with /info, /health, /<agent>
uvicorn.run(app, port=8080)
```

```
Routes:
  POST /<agent-name>   AG-UI RunAgentInput → SSE stream
  GET  /info           Agent discovery
  GET  /health         Health check
```

### DifyClient (low-level)

```python
client = DifyClient(config)
async for evt in client.stream_chat(query="Hello", inputs={}): ...
async for evt in client.stream_workflow(inputs={"url": "..."}): ...
async for evt in client.stream_completion(inputs={}): ...
await client.stop_chat(task_id="...")
```

## Project Structure

```
ag_ui_dify/
├── __init__.py           # Package exports
├── types.py              # Dify type definitions (Pydantic models)
├── dify_client.py        # Async HTTP client for all Dify endpoints
├── event_translator.py   # Event translators (Chat/Agent/Workflow/Completion)
├── agent.py              # DifyAgent main adapter
└── server.py             # Starlette single-port multi-agent server
```

## Verification Status

All 4 Dify app types verified against a real Dify instance:

| App Type | Status | Coverage |
|---|---|---|
| Agent | ✓ | Tool calls, reasoning chain, multi-turn conversation |
| Workflow | ✓ | Node execution, agent_log sub-steps, text output |
| Chat | ✓ | Streaming text, message lifecycle |
| Completion | ✓ | Streaming text, `<think>` → REASONING events |

## Requirements

- Python >= 3.9
- ag-ui-protocol >= 0.1.17
- httpx >= 0.27.0
- pydantic >= 2.11.0
- starlette >= 0.40.0 (optional, for HTTP server)
- uvicorn (optional, for HTTP server)

## License

MIT
