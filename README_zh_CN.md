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

## CopilotKit 集成

适配器原生支持 AG-UI 协议，可通过 `@ag-ui/client` 的 `HttpAgent` 与 CopilotKit 无缝对接。

### 架构

```
CopilotKit 前端 (React)
  │  <CopilotKit runtimeUrl="/api/copilotkit">
  │    <CopilotChat agentId="company-paper" />
  │  </CopilotKit>
  ▼
CopilotKit Runtime (Next.js API Route)
  │  new CopilotRuntime({
  │    agents: {
  │      "company-paper": new HttpAgent({ url: "http://adapter:8080/company-paper" }),
  │      "market-research": new HttpAgent({ url: "http://adapter:8080/market-research" }),
  │    }
  │  })
  ▼
ag-ui-dify-adapter (单端口，多路径)
  │  POST /company-paper   → Agent（公司一页纸）
  │  POST /market-research → Workflow（市场调研）
  │  → text/event-stream（AG-UI SSE 事件）
  ▼
Dify API
```

### 步骤 1 — 启动适配器

```bash
# 单个 Agent
DIFY_API_KEY=app-xxx \
DIFY_APP_TYPE=agent \
uvicorn ag_ui_dify:create_app --port 8080

# 多个 Agent
DIFY_AGENTS='{
  "company-paper": {"key": "app-xxx", "type": "agent"},
  "market-research": {"key": "app-yyy", "type": "workflow"}
}' \
uvicorn ag_ui_dify:create_app --port 8080
```

或使用 Docker Compose：

```bash
docker compose --env-file .env up -d
```

所有 Agent 从单一端口提供服务，按路径路由。

### 步骤 2 — 配置 CopilotKit Runtime

```ts
// app/api/copilotkit/route.ts (Next.js App Router)
import { NextRequest } from "next/server";
import {
  CopilotRuntime,
  ExperimentalEmptyAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
} from "@copilotkit/runtime";
import { HttpAgent } from "@ag-ui/client";

const ADAPTER = process.env.DIFY_ADAPTER_URL || "http://localhost:8080";

const runtime = new CopilotRuntime({
  agents: {
    "company-paper": new HttpAgent({ url: `${ADAPTER}/company-paper` }),
    "market-research": new HttpAgent({ url: `${ADAPTER}/market-research` }),
    "meeting-bot": new HttpAgent({ url: `${ADAPTER}/meeting-bot` }),
    "code-convert": new HttpAgent({ url: `${ADAPTER}/code-convert` }),
  },
});

const serviceAdapter = new ExperimentalEmptyAdapter();

export const POST = (req: NextRequest) => {
  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    endpoint: "/api/copilotkit",
    serviceAdapter,
    runtime,
  });
  return handleRequest(req);
};
```

### 步骤 3 — 前端

```tsx
import { CopilotKit } from "@copilotkit/react-core";
import { CopilotChat } from "@copilotkit/react-ui";
import "@copilotkit/react-ui/styles.css";

export default function App() {
  return (
    <CopilotKit runtimeUrl="/api/copilotkit">
      <CopilotChat agentId="company-paper" />
    </CopilotKit>
  );
}
```

### Docker Compose

```yaml
services:
  adapter:
    build: .
    ports: ["8080:8080"]
    environment:
      DIFY_BASE_URL: http://dify-server/v1
      DIFY_AGENTS: |
        {
          "company-paper": {"key": "${API_KEY_1}", "type": "agent"},
          "market-research": {"key": "${API_KEY_2}", "type": "workflow"},
          "meeting-bot": {"key": "${API_KEY_3}", "type": "chat"},
          "code-convert": {"key": "${API_KEY_4}", "type": "completion"}
        }
```

API key 通过 `.env` 文件的 `${VAR}` 语法注入，不会暴露到前端。

## 依赖

- Python >= 3.9
- ag-ui-protocol >= 0.1.17
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

全部 4 种 Dify 应用类型已在真实 Dify 实例上完成验证：

| App 类型 | 实际 Dify 环境 | 验证内容 |
|---|---|---|
| Agent（智能体） | ✅ | 工具调用、思考链、多轮对话 |
| Workflow（工作流） | ✅ | 节点执行、Agent 子步骤、文本输出 |
| Chat（对话） | ✅ | 流式文本、消息生命周期 |
| Completion（文本生成） | ✅ | 流式文本、输入变量 |

## License

MIT
