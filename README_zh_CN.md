# ag-ui-dify-adapter

AG-UI 协议 Dify 适配器 — 将 [Dify](https://dify.ai) API 响应转换为 [AG-UI](https://ag-ui.com) 流式事件，使 Dify 驱动的 AI Agent 能够集成到任何兼容 AG-UI 的前端应用中。

## 特性

- **全部 5 种 Dify 应用类型**：Chatbot（对话）、Chatflow（对话流）、Agent（智能体）、Workflow（工作流）、Completion（文本生成）
- **24+ 种 AG-UI 事件**：TEXT_MESSAGE、TOOL_CALL、TOOL_CALL_RESULT、REASONING、STATE_SNAPSHOT、MESSAGES_SNAPSHOT、STEP、CUSTOM、RAW、RUN
- **工具调用全流程**：`TOOL_CALL_START` → `ARGS` → `END` → `RESULT`，覆盖 Agent ReAct 循环
- **推理事件**：流式 `<think>` 标签检测 → `REASONING_START/MESSAGE_START/CONTENT/MESSAGE_END/END`
- **快照**：每次 run 开始时自动发送 `MESSAGES_SNAPSHOT` + `STATE_SNAPSHOT`
- **流式输出**：实时文本流式，自动分离 `<think>` 推理块
- **多轮对话**：`thread_id` ↔ `conversation_id` 映射追踪
- **状态与上下文**：AG-UI state/context → Dify input 变量
- **单端口多 Agent**：一个端口，多个 Dify App 按路径路由
- **YAML 配置**：清爽的 `config.yaml`，告别塞在环境变量里的 JSON
- **.env 自动加载**：通过 python-dotenv 自动读取 `.env` 文件
- **RAW 透传**：未识别的 Dify 事件以 `RAW` 透传，不丢弃
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
        app_type=DifyAppType.AGENT,
    ))

    input = RunAgentInput(
        thread_id="thread-1",
        run_id="run-1",
        state=None,
        messages=[UserMessage(id="u1", role="user", content="你好！")],
        tools=[], context=[], forwarded_props={},
    )

    async for event in agent.run(input):
        print(event.model_dump_json(by_alias=True))

asyncio.run(main())
```

### HTTP 服务

三种配置方式，任选其一：

**YAML 配置文件（推荐）：**

```yaml
# config.yaml
base_url: http://localhost/v1
agents:
  agent-a:
    key: app-xxx
    type: agent
  wf-b:
    key: app-yyy
    type: workflow
```

```bash
uvicorn ag_ui_dify:create_app --port 8080
```

**环境变量：**

```bash
# 单个 Agent
DIFY_API_KEY=app-xxx DIFY_APP_TYPE=agent \
  uvicorn ag_ui_dify:create_app --port 8080

# 多个 Agent（单端口）
DIFY_AGENTS='{"agent-a":{"key":"app-xxx","type":"agent"}}' \
  uvicorn ag_ui_dify:create_app --port 8080
```

**.env 文件（自动加载）：**

```bash
# .env
DIFY_AGENTS={"agent-a":{"key":"app-xxx","type":"agent"}}
```

```bash
uvicorn ag_ui_dify:create_app --port 8080
```

API key 始终在服务端，不经过客户端。

```bash
# 端点
curl -X POST http://localhost:8080/agent-a \
  -H "Content-Type: application/json" \
  -d '{"threadId":"t1","runId":"r1","messages":[{"id":"u1","role":"user","content":"你好"}],"tools":[],"context":[]}'

curl http://localhost:8080/health   # → {"status":"ok"}
curl http://localhost:8080/info     # → agent 发现
```

## Dify → AG-UI 事件映射

### Agent（智能体）应用

| Dify SSE 事件 | AG-UI 事件 |
|---|---|
| `agent_thought`（带思考内容） | `STEP_STARTED` + `CUSTOM`（思考） |
| `agent_thought`（带工具调用） | `TOOL_CALL_START` + `TOOL_CALL_ARGS` + `TOOL_CALL_END` |
| `agent_thought`（带观察结果） | `TOOL_CALL_RESULT` |
| `agent_message`（首条） | `TEXT_MESSAGE_START` |
| `agent_message` | `TEXT_MESSAGE_CONTENT`（`<think>` → `REASONING`） |
| `message_replace` | `CUSTOM` |
| `message_file` | `CUSTOM` |
| `message_end` | `TEXT_MESSAGE_END` + `RUN_FINISHED` |

### Workflow（工作流）应用

| Dify SSE 事件 | AG-UI 事件 |
|---|---|
| `workflow_started` | `RUN_STARTED` + `TEXT_MESSAGE_START` |
| `node_started` / `node_retry` | `STEP_STARTED` |
| `node_finished` | `STEP_FINISHED` |
| `agent_log` | `STEP_STARTED` / `STEP_FINISHED` |
| `iteration_started/completed` | `STEP_STARTED` / `STEP_FINISHED` |
| `loop_started/completed` | `STEP_STARTED` / `STEP_FINISHED` |
| `text_chunk` | `TEXT_MESSAGE_CONTENT`（`<think>` → `REASONING`） |
| `text_replace` | `CUSTOM` |
| `workflow_paused` | `CUSTOM` + `RUN_FINISHED` |
| `human_input_*` | `CUSTOM` |
| `workflow_finished` | `TEXT_MESSAGE_END` + `RUN_FINISHED` |

### Chatbot（对话）/ Chatflow（对话流）/ Completion（文本生成）应用

Chatbot（chat）、Chatflow（advanced-chat）和 Completion 使用相同的事件格式 — `message` 输出文本，`message_end` 结束。

| Dify SSE 事件 | AG-UI 事件 |
|---|---|
| `message`（首条） | `TEXT_MESSAGE_START` |
| `message` | `TEXT_MESSAGE_CONTENT`（`<think>` → `REASONING`） |
| `message_replace` | `CUSTOM` |
| `message_file` | `CUSTOM` |
| `tts_message` / `tts_message_end` | `CUSTOM` |
| `message_end` | `TEXT_MESSAGE_END` + `RUN_FINISHED` |

**所有应用类型**：开始发送 `MESSAGES_SNAPSHOT` + `STATE_SNAPSHOT`，出错发送 `RUN_ERROR`，忽略 `ping`，未知事件 → `RAW`。

## API 参考

### DifyAgent

```python
agent = DifyAgent(DifyConfig(
    api_key="app-xxx",           # 必填：Dify API 密钥
    base_url="...",              # 默认：https://api.dify.ai/v1
    app_type=DifyAppType.AGENT,  # 不指定则自动检测
    user="ag-ui-user",           # 默认用户标识
    timeout=120.0,               # HTTP 超时时间（秒）
))
async for event in agent.run(run_input):
    ...
```

### HTTP Server

```python
from ag_ui_dify import create_app, load_agents
import uvicorn

agents = load_agents()  # 从 DIFY_AGENTS / DIFY_API_KEY 环境变量读取
app = create_app()      # Starlette app，含 /info /health /<agent>
uvicorn.run(app, port=8080)
```

```
路由：
  POST /<agent-name>   AG-UI RunAgentInput → SSE 流
  GET  /info           Agent 发现
  GET  /health         健康检查
```

### DifyClient（底层）

```python
client = DifyClient(config)
async for evt in client.stream_chat(query="你好", inputs={}): ...
async for evt in client.stream_workflow(inputs={"url": "..."}): ...
async for evt in client.stream_completion(inputs={}): ...
await client.stop_chat(task_id="...")
```

## 项目结构

```
ag_ui_dify/
├── __init__.py           # 包导出
├── types.py              # Dify 类型定义（Pydantic 模型）
├── dify_client.py        # Dify API 异步 HTTP 客户端
├── event_translator.py   # 事件转换器（Chat/Agent/Workflow/Completion）
├── agent.py              # DifyAgent 主适配器
└── server.py             # Starlette 单端口多 Agent 服务
```

## 验证状态

全部 4 种 Dify 应用类型已在真实 Dify 实例上完成验证：

| App 类型 | 状态 | 覆盖内容 |
|---|---|---|
| Agent（智能体） | ✓ | 工具调用、思考链、多轮对话 |
| Workflow（工作流） | ✓ | 节点执行、agent_log 子步骤、文本输出 |
| Chat（对话） | ✓ | 流式文本、消息生命周期 |
| Completion（文本生成） | ✓ | 流式文本、`<think>` → REASONING 事件 |

## 依赖

- Python >= 3.9
- ag-ui-protocol >= 0.1.17
- httpx >= 0.27.0
- pydantic >= 2.11.0
- starlette >= 0.40.0（可选，用于 HTTP 服务）
- uvicorn（可选，用于 HTTP 服务）

## License

MIT
