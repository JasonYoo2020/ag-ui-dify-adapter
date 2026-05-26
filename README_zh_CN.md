# ag-ui-dify-adapter

AG-UI 协议 Dify 适配器 — 将 [Dify](https://dify.ai) API 响应转换为 [AG-UI](https://ag-ui.com) 流式事件，使 Dify 驱动的 AI Agent 能够集成到任何兼容 AG-UI 的前端应用中。

## 特性

- **全部 4 种 Dify 应用类型**：Chat（对话）、Agent（智能体）、Workflow（工作流）、Completion（文本生成）
- **完整事件映射**：将全部 Dify SSE 事件映射为 AG-UI 的 17 种标准事件类型
- **工具调用支持**：Agent 工具调用（ReAct 循环）转换为 `TOOL_CALL_START/ARGS/END`
- **实时流式输出**：通过 `TEXT_MESSAGE_START/CONTENT/END` 实现逐 token 流式文本输出
- **多轮对话**：`thread_id` ↔ `conversation_id` 映射追踪
- **状态与上下文**：AG-UI 的 state/context/forwardedProps → Dify 的 input 变量
- **文件支持**：通过 Dify 文件上传 API 支持文件附件
- **HTTP 服务**：内置 Starlette SSE 流式端点
- **全异步**：基于 `httpx` 的完整异步支持

## 安装

```bash
pip install ag-ui-dify-adapter
```

如需 HTTP 服务端：

```bash
pip install ag-ui-dify-adapter[server]
```

## 快速开始

### 作为库使用

```python
import asyncio
from ag_ui_dify import DifyAgent, DifyConfig, DifyAppType
from ag_ui.core import RunAgentInput, UserMessage

async def main():
    agent = DifyAgent(DifyConfig(
        api_key="app-xxx",
        base_url="https://api.dify.ai/v1",
        app_type=DifyAppType.AGENT,  # 不指定则自动检测
    ))

    input = RunAgentInput(
        thread_id="thread-1",
        run_id="run-1",
        state=None,
        messages=[UserMessage(id="u1", role="user", content="你好！")],
        tools=[],
        context=[],
        forwarded_props={},
    )

    async for event in agent.run(input):
        print(event.model_dump_json(by_alias=True))

asyncio.run(main())
```

### 作为 HTTP 服务运行

```python
from ag_ui_dify import create_app
import uvicorn

app = create_app()
uvicorn.run(app, host="0.0.0.0", port=8080)
```

发送请求：

```bash
curl -X POST http://localhost:8080/ \
  -H "Content-Type: application/json" \
  -d '{
    "threadId": "t1",
    "runId": "r1",
    "messages": [{"id": "u1", "role": "user", "content": "你好！"}],
    "tools": [],
    "context": [],
    "forwardedProps": {
      "apiKey": "app-xxx",
      "baseUrl": "https://api.dify.ai/v1",
      "appType": "agent"
    }
  }'
```

## Dify → AG-UI 事件映射

### Agent（智能体）应用

| Dify SSE 事件 | AG-UI 事件 |
|---|---|
| `agent_thought`（带思考内容） | `STEP_STARTED` + `CUSTOM`（思考） |
| `agent_thought`（带工具调用） | `TOOL_CALL_START` + `TOOL_CALL_ARGS` + `TOOL_CALL_END` |
| `agent_thought`（带观察结果） | `CUSTOM`（观察）+ `STEP_FINISHED` |
| `agent_message`（首条） | `TEXT_MESSAGE_START` |
| `agent_message` | `TEXT_MESSAGE_CONTENT` |
| `message_end` | `TEXT_MESSAGE_END` + `RUN_FINISHED` |

### Workflow（工作流）应用

| Dify SSE 事件 | AG-UI 事件 |
|---|---|
| `workflow_started` | `RUN_STARTED` |
| `node_started` | `STEP_STARTED` |
| `agent_log` | `STEP_STARTED` / `STEP_FINISHED` |
| `text_chunk` | `TEXT_MESSAGE_CONTENT` |
| `node_finished` | `STEP_FINISHED` |
| `workflow_finished` | `TEXT_MESSAGE_END` + `RUN_FINISHED` |

### Chat（对话）应用

| Dify SSE 事件 | AG-UI 事件 |
|---|---|
| `message`（首条） | `TEXT_MESSAGE_START` |
| `message` | `TEXT_MESSAGE_CONTENT` |
| `message_end` | `TEXT_MESSAGE_END` + `RUN_FINISHED` |
| `message_file` | `CUSTOM` |

### Completion（文本生成）应用

| Dify SSE 事件 | AG-UI 事件 |
|---|---|
| `message`（首条） | `TEXT_MESSAGE_START` |
| `message` | `TEXT_MESSAGE_CONTENT` |
| `message_end` | `TEXT_MESSAGE_END` + `RUN_FINISHED` |

所有应用类型：开头均发送 `RUN_STARTED`，出错时发送 `RUN_ERROR`，`ping` 心跳事件被忽略。

## API 参考

### DifyAgent

```python
agent = DifyAgent(DifyConfig(
    api_key="app-xxx",            # 必填：Dify API 密钥
    base_url="...",               # 默认：https://api.dify.ai/v1
    app_type=DifyAppType.AGENT,   # 不指定则自动检测
    user="ag-ui-user",            # 默认用户标识
    timeout=120.0,                # HTTP 超时时间（秒）
))

async for event in agent.run(run_input):
    ...
```

### DifyClient

底层异步客户端，覆盖全部 Dify API 端点：

```python
client = DifyClient(config)
async for evt in client.stream_chat(query="你好", inputs={}):
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

## 依赖

- Python >= 3.9
- ag-ui-protocol >= 0.1.5
- httpx >= 0.27.0
- pydantic >= 2.11.0
- starlette >= 0.40.0（可选，用于 HTTP 服务）
- uvicorn（可选，用于 HTTP 服务）

## 项目结构

```
ag_ui_dify/
├── __init__.py           # 包导出
├── types.py              # Dify 类型定义（Pydantic 模型）
├── dify_client.py        # Dify API 异步 HTTP 客户端
├── event_translator.py   # 事件转换器（Chat/Agent/Workflow/Completion）
├── agent.py              # DifyAgent 主适配器
└── server.py             # Starlette HTTP SSE 端点
tests/
├── test_types.py         # 类型模型测试（19 个）
├── test_translator.py    # 转换器测试（14 个）
├── test_client.py        # 客户端测试（5 个）
├── test_agent.py         # Agent 测试（10 个）
└── test_integration.py   # 实际环境集成测试
```

## 验证状态

| App 类型 | 实际 Dify 环境 | 测试状态 |
|---|---|---|
| Agent（智能体） | ✅ 已测试 | 工具调用、思考链、多轮对话全部通过 |
| Workflow（工作流） | ✅ 已测试 | 节点执行、Agent 子步骤、文本输出全部通过 |
| Chat（对话） | ✅ 已测试 | 流式文本、消息生命周期全部通过 |
| Completion（文本生成） | ⬜ 未实测 | 单元测试覆盖 |

## License

MIT
