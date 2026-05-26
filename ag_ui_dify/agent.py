"""DifyAgent — the main AG-UI adapter for Dify.

Accepts RunAgentInput, translates it to Dify API calls, and streams
AG-UI events back. Emits STATE_SNAPSHOT and MESSAGES_SNAPSHOT at
the start of each run.
"""

from typing import Any, AsyncGenerator, Dict, List, Optional

from ag_ui.core import (
    BaseEvent,
    EventType,
    MessagesSnapshotEvent,
    RunAgentInput,
    RunErrorEvent,
    StateSnapshotEvent,
)

from .dify_client import DifyClient
from .event_translator import (
    AgentTranslator,
    BaseTranslator,
    ChatTranslator,
    CompletionTranslator,
    WorkflowTranslator,
)
from .types import DifyAppType, DifyConfig


class DifyAgent:
    """AG-UI compatible agent backed by a Dify application.

    Usage::

        agent = DifyAgent(DifyConfig(
            api_key="app-xxx",
            base_url="https://api.dify.ai/v1",
        ))
        async for event in agent.run(run_input):
            print(event.model_dump_json(by_alias=True))
    """

    def __init__(self, config: DifyConfig):
        self._config = config
        self._conversations: Dict[str, str] = {}

    def _get_conversation_id(self, thread_id: str) -> str:
        return self._conversations.get(thread_id, "")

    def _set_conversation_id(self, thread_id: str, conversation_id: str):
        if conversation_id:
            self._conversations[thread_id] = conversation_id

    def _extract_query(self, input: RunAgentInput) -> str:
        for msg in reversed(input.messages):
            role = getattr(msg, "role", None)
            if role == "user":
                content = getattr(msg, "content", None)
                if content:
                    return str(content)
        return ""

    def _build_inputs(self, input: RunAgentInput) -> Dict[str, Any]:
        inputs: Dict[str, Any] = {}

        if isinstance(input.state, dict):
            inputs.update(input.state)
        elif input.state is not None:
            inputs["state"] = input.state

        for ctx in input.context or []:
            inputs[ctx.description] = ctx.value

        if isinstance(input.forwarded_props, dict):
            extra = input.forwarded_props.get("inputs")
            if isinstance(extra, dict):
                inputs.update(extra)

        return inputs

    def _extract_files(self, input: RunAgentInput) -> List[Dict[str, Any]]:
        if isinstance(input.forwarded_props, dict):
            files = input.forwarded_props.get("files")
            if isinstance(files, list):
                return files
        return []

    async def run(
        self, input: RunAgentInput
    ) -> AsyncGenerator[BaseEvent, None]:
        """Execute an AG-UI run against the Dify API.

        Emits STATE_SNAPSHOT and MESSAGES_SNAPSHOT at start,
        followed by the translated Dify SSE event stream.
        """
        # Emit initial snapshots
        if input.messages:
            yield MessagesSnapshotEvent(
                type=EventType.MESSAGES_SNAPSHOT,
                messages=input.messages,
            )
        if input.state is not None:
            yield StateSnapshotEvent(
                type=EventType.STATE_SNAPSHOT,
                snapshot=input.state,
            )

        client = DifyClient(self._config)
        try:
            app_type = self._config.app_type or await client.detect_app_type()
            query = self._extract_query(input)
            inputs = self._build_inputs(input)
            files = self._extract_files(input)
            thread_id = input.thread_id
            run_id = input.run_id
            conversation_id = self._get_conversation_id(thread_id)

            translator = self._create_translator(app_type, thread_id, run_id)

            if app_type == DifyAppType.WORKFLOW:
                event_stream = client.stream_workflow(
                    inputs=inputs, user=self._config.user,
                )
            elif app_type == DifyAppType.COMPLETION:
                event_stream = client.stream_completion(
                    inputs=inputs, files=files, user=self._config.user,
                )
            else:
                event_stream = client.stream_chat(
                    query=query,
                    inputs=inputs,
                    conversation_id=conversation_id,
                    files=files,
                    user=self._config.user,
                )

            async for agui_event in translator.translate(event_stream):
                yield agui_event

            if translator.conversation_id:
                self._set_conversation_id(thread_id, translator.conversation_id)

        except Exception as e:
            # Sanitize — never include raw httpx errors that may contain headers
            msg = str(e)
            if len(msg) > 500:
                msg = msg[:500] + "...(truncated)"
            yield RunErrorEvent(type=EventType.RUN_ERROR, message=msg)

        finally:
            await client.close()

    def _create_translator(
        self, app_type: DifyAppType, thread_id: str, run_id: str
    ) -> BaseTranslator:
        if app_type == DifyAppType.AGENT:
            return AgentTranslator(thread_id, run_id)
        elif app_type == DifyAppType.WORKFLOW:
            return WorkflowTranslator(thread_id, run_id)
        elif app_type == DifyAppType.COMPLETION:
            return CompletionTranslator(thread_id, run_id)
        else:
            return ChatTranslator(thread_id, run_id)
