"""AG-UI Dify Adapter — translate Dify API responses to AG-UI streaming events.

Supports all 4 Dify app types (Chat, Agent, Workflow, Completion) with
comprehensive event mapping including:
- 17+ AG-UI event types: TEXT_MESSAGE, TOOL_CALL, TOOL_CALL_RESULT,
  REASONING, STATE_SNAPSHOT, MESSAGES_SNAPSHOT, STEP, CUSTOM, RAW, etc.
- Streaming <think> tag detection → REASONING events
- 30+ Dify SSE event types handled
"""

from .agent import DifyAgent
from .dify_client import DifyClient
from .event_translator import (
    AgentTranslator,
    ChatTranslator,
    CompletionTranslator,
    WorkflowTranslator,
)
from .types import (
    ConversationMapping,
    DifyAppType,
    DifyChatRequest,
    DifyCompletionRequest,
    DifyConfig,
    DifyFile,
    DifyStreamEvent,
    DifyWorkflowRequest,
)
from .server import (
    _parse_run_input,
    agui_endpoint,
    create_app,
    create_dify_agent_from_forwarded_props,
    sse_stream,
)

__all__ = [
    "DifyAgent",
    "DifyClient",
    "DifyConfig",
    "DifyAppType",
    "DifyStreamEvent",
    "DifyChatRequest",
    "DifyWorkflowRequest",
    "DifyCompletionRequest",
    "DifyFile",
    "ConversationMapping",
    "ChatTranslator",
    "AgentTranslator",
    "WorkflowTranslator",
    "CompletionTranslator",
    "create_app",
    "agui_endpoint",
    "create_dify_agent_from_forwarded_props",
    "sse_stream",
    "_parse_run_input",
]
