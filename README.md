# ag-ui-dify-adapter

AG-UI protocol adapter for Dify — translates [Dify](https://dify.ai) API responses to [AG-UI](https://ag-ui.com) streaming events, enabling Dify-powered AI agents to integrate with any AG-UI-compatible frontend.

## Features

- **All 4 Dify app types**: Chat, Agent, Workflow, Completion
- **Complete event mapping**: Maps all Dify SSE events to AG-UI's 17 standard event types
- **Tool call support**: Agent tool calls (ReAct loops) translated to `TOOL_CALL_START/ARGS/END`
- **Streaming**: Real-time text streaming via `TEXT_MESSAGE_START/CONTENT/END`
- **Multi-turn conversation**: `thread_id` ↔ `conversation_id` tracking
- **State & context**: AG-UI state/context/forwardedProps → Dify input variables
- **File support**: File attachments via Dify's file upload API
- **HTTP server**: Built-in Starlette endpoint with SSE streaming
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

### Usage as a library

```python
import asyncio
from ag_ui_dify import DifyAgent, DifyConfig, DifyAppType
from ag_ui.core import RunAgentInput, UserMessage

async def main():
    agent = DifyAgent(DifyConfig(
        api_key="app-xxx",
        base_url="https://api.dify.ai/v1",
        app_type=DifyAppType.AGENT,  # auto-detected if omitted
    ))

    input = RunAgentInput(
        thread_id="thread-1",
        run_id="run-1",
        state=None,
        messages=[UserMessage(id="u1", role="user", content="Hello!")],
        tools=[],
        context=[],
        forwarded_props={},
    )

    async for event in agent.run(input):
        print(event.model_dump_json(by_alias=True))

asyncio.run(main())
```

### Usage as an HTTP server

```python
from ag_ui_dify import create_app
import uvicorn

app = create_app()
uvicorn.run(app, host="0.0.0.0", port=8080)
```

Then send requests:

```bash
curl -X POST http://localhost:8080/ \
  -H "Content-Type: application/json" \
  -d '{
    "threadId": "t1",
    "runId": "r1",
    "messages": [{"id": "u1", "role": "user", "content": "Hello!"}],
    "tools": [],
    "context": [],
    "forwardedProps": {
      "apiKey": "app-xxx",
      "baseUrl": "https://api.dify.ai/v1",
      "appType": "agent"
    }
  }'
```

## Dify → AG-UI Event Mapping

### Agent App

| Dify SSE Event | AG-UI Event(s) |
|---|---|
| `agent_thought` (with thought) | `STEP_STARTED` + `CUSTOM` (thought) |
| `agent_thought` (with tool) | `TOOL_CALL_START` + `TOOL_CALL_ARGS` + `TOOL_CALL_END` |
| `agent_thought` (with observation) | `CUSTOM` (observation) + `STEP_FINISHED` |
| `agent_message` (first) | `TEXT_MESSAGE_START` |
| `agent_message` | `TEXT_MESSAGE_CONTENT` |
| `message_end` | `TEXT_MESSAGE_END` + `RUN_FINISHED` |

### Workflow App

| Dify SSE Event | AG-UI Event(s) |
|---|---|
| `workflow_started` | `RUN_STARTED` |
| `node_started` | `STEP_STARTED` |
| `agent_log` | `STEP_STARTED` / `STEP_FINISHED` |
| `text_chunk` | `TEXT_MESSAGE_CONTENT` |
| `node_finished` | `STEP_FINISHED` |
| `workflow_finished` | `TEXT_MESSAGE_END` + `RUN_FINISHED` |

### Chat App

| Dify SSE Event | AG-UI Event(s) |
|---|---|
| `message` (first) | `TEXT_MESSAGE_START` |
| `message` | `TEXT_MESSAGE_CONTENT` |
| `message_end` | `TEXT_MESSAGE_END` + `RUN_FINISHED` |
| `message_file` | `CUSTOM` |

### Completion App

| Dify SSE Event | AG-UI Event(s) |
|---|---|
| `message` (first) | `TEXT_MESSAGE_START` |
| `message` | `TEXT_MESSAGE_CONTENT` |
| `message_end` | `TEXT_MESSAGE_END` + `RUN_FINISHED` |

All app types: `RUN_STARTED` at the beginning, `RUN_ERROR` on error, `ping` ignored.

## API Reference

### DifyAgent

```python
agent = DifyAgent(DifyConfig(
    api_key="app-xxx",       # Required: Dify API key
    base_url="...",          # Default: https://api.dify.ai/v1
    app_type=DifyAppType.AGENT,  # Auto-detected if omitted
    user="ag-ui-user",       # Default user identifier
    timeout=120.0,           # HTTP timeout in seconds
))

async for event in agent.run(run_input):
    ...
```

### DifyClient

Low-level async client for all Dify API endpoints:

```python
client = DifyClient(config)
async for evt in client.stream_chat(query="Hello", inputs={}):
    ...
async for evt in client.stream_workflow(inputs={"url": "..."}):
    ...
async for evt in client.stream_completion(inputs={}):
    ...
await client.stop_chat(task_id="...")
messages = await client.get_messages(conversation_id="...", user="...")
convs = await client.get_conversations(user="...")
upload_result = await client.upload_file(file_path="...", user="...")
```

## Project Structure

```
ag_ui_dify/
├── __init__.py           # Package exports
├── types.py              # Dify type definitions (Pydantic models)
├── dify_client.py        # Async HTTP client for all Dify endpoints
├── event_translator.py   # Event translators (Chat/Agent/Workflow/Completion)
├── agent.py              # DifyAgent main adapter
└── server.py             # Starlette HTTP SSE endpoint
tests/
├── test_types.py         # Type model tests (19)
├── test_translator.py    # Translator tests (14)
├── test_client.py        # Client tests (5)
├── test_agent.py         # Agent tests (10)
└── test_integration.py   # Real-environment integration tests
```

## Verification Status

All 4 Dify app types have been verified against a real Dify instance:

| App Type | Real Dify Tested | Notes |
|---|---|---|
| Agent | ✓ | Tool calls, reasoning chain, multi-turn conversation |
| Workflow | ✓ | Node execution, agent_log sub-steps, text output |
| Chat | ✓ | Streaming text, message lifecycle |
| Completion | ✓ | Streaming text, input variables |

## Requirements

- Python >= 3.9
- ag-ui-protocol >= 0.1.17
- httpx >= 0.27.0
- pydantic >= 2.11.0
- starlette >= 0.40.0 (optional, for HTTP server)
- uvicorn (optional, for HTTP server)

## License

MIT
