"""Dify SSE event → AG-UI event translators for each Dify app type."""

import uuid
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    EventType,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StepFinishedEvent,
    StepStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)

from .types import DifyStreamEvent


def _new_id() -> str:
    return uuid.uuid4().hex


class BaseTranslator(ABC):
    """Base class for Dify-to-AG-UI event translators.

    Each Dify app type has its own translator subclass.
    """

    def __init__(self, thread_id: str, run_id: str):
        self.thread_id = thread_id
        self.run_id = run_id
        self._message_id: Optional[str] = None
        self._message_started = False
        self._finished = False
        self.conversation_id: Optional[str] = None

    @abstractmethod
    async def translate(
        self, events: AsyncGenerator[DifyStreamEvent, None]
    ) -> AsyncGenerator[BaseEvent, None]:
        """Translate a stream of Dify events to AG-UI events."""
        ...

    def _track_conversation(self, evt: DifyStreamEvent):
        if evt.conversation_id:
            self.conversation_id = evt.conversation_id

    # Helper factory methods to reduce repetition

    def _run_started(self) -> RunStartedEvent:
        return RunStartedEvent(
            type=EventType.RUN_STARTED,
            thread_id=self.thread_id,
            run_id=self.run_id,
        )

    def _run_finished(self) -> RunFinishedEvent:
        return RunFinishedEvent(
            type=EventType.RUN_FINISHED,
            thread_id=self.thread_id,
            run_id=self.run_id,
        )

    def _run_error(self, message: str, code: Optional[str] = None) -> RunErrorEvent:
        return RunErrorEvent(
            type=EventType.RUN_ERROR,
            message=message,
            code=code,
        )

    def _text_message_start(self) -> TextMessageStartEvent:
        return TextMessageStartEvent(
            type=EventType.TEXT_MESSAGE_START,
            message_id=self._message_id,
            role="assistant",
        )

    def _text_message_content(self, delta: str) -> TextMessageContentEvent:
        return TextMessageContentEvent(
            type=EventType.TEXT_MESSAGE_CONTENT,
            message_id=self._message_id,
            delta=delta,
        )

    def _text_message_end(self) -> TextMessageEndEvent:
        return TextMessageEndEvent(
            type=EventType.TEXT_MESSAGE_END,
            message_id=self._message_id,
        )

    def _tool_call_start(self, tool_call_id: str, tool_name: str) -> ToolCallStartEvent:
        return ToolCallStartEvent(
            type=EventType.TOOL_CALL_START,
            tool_call_id=tool_call_id,
            tool_call_name=tool_name,
            parent_message_id=self._message_id,
        )

    def _tool_call_args(self, tool_call_id: str, delta: str) -> ToolCallArgsEvent:
        return ToolCallArgsEvent(
            type=EventType.TOOL_CALL_ARGS,
            tool_call_id=tool_call_id,
            delta=delta,
        )

    def _tool_call_end(self, tool_call_id: str) -> ToolCallEndEvent:
        return ToolCallEndEvent(
            type=EventType.TOOL_CALL_END,
            tool_call_id=tool_call_id,
        )

    def _step_started(self, step_name: str) -> StepStartedEvent:
        return StepStartedEvent(
            type=EventType.STEP_STARTED,
            step_name=step_name,
        )

    def _step_finished(self, step_name: str) -> StepFinishedEvent:
        return StepFinishedEvent(
            type=EventType.STEP_FINISHED,
            step_name=step_name,
        )

    def _custom(self, name: str, value: dict) -> CustomEvent:
        return CustomEvent(
            type=EventType.CUSTOM,
            name=name,
            value=value,
        )


class ChatTranslator(BaseTranslator):
    """Translates Dify Chat app SSE events to AG-UI events."""

    async def translate(
        self, events: AsyncGenerator[DifyStreamEvent, None]
    ) -> AsyncGenerator[BaseEvent, None]:
        yield self._run_started()

        async for evt in events:
            if evt.event == "ping":
                continue

            if evt.event == "error":
                yield self._run_error(evt.message or "Unknown Dify error", evt.code)
                return

            if evt.event == "message":
                if not self._message_started:
                    self._message_started = True
                    self._message_id = evt.message_id or evt.id or _new_id()
                    yield self._text_message_start()
                if evt.answer:
                    yield self._text_message_content(evt.answer)

            elif evt.event == "message_file":
                yield self._custom("message_file", {
                    "message_id": evt.message_id,
                    "data": evt.extra,
                })

            elif evt.event == "message_end":
                self._track_conversation(evt)
                self._end_message()
                if self._message_id:
                    yield self._text_message_end()
                self._finished = True
                yield self._run_finished()
                return

            elif evt.event == "tts_message":
                if evt.audio:
                    yield self._custom("tts_message", {"audio": evt.audio})

            elif evt.event == "tts_message_end":
                yield self._custom("tts_message_end", {})

        if not self._finished:
            self._end_message()
            if self._message_id:
                yield self._text_message_end()
            yield self._run_finished()

    def _end_message(self):
        self._message_started = False


class AgentTranslator(BaseTranslator):
    """Translates Dify Agent app SSE events to AG-UI events."""

    def __init__(self, thread_id: str, run_id: str):
        super().__init__(thread_id, run_id)
        self._current_step: Optional[str] = None
        self._current_tool_call_id: Optional[str] = None

    async def translate(
        self, events: AsyncGenerator[DifyStreamEvent, None]
    ) -> AsyncGenerator[BaseEvent, None]:
        yield self._run_started()

        async for evt in events:
            if evt.event == "ping":
                continue

            if evt.event == "error":
                yield self._run_error(evt.message or "Unknown Dify error", evt.code)
                return

            if evt.event == "agent_thought":
                async for e in self._handle_agent_thought(evt):
                    yield e

            elif evt.event == "agent_message":
                if not self._message_started:
                    self._message_started = True
                    self._message_id = evt.message_id or evt.id or _new_id()
                    yield self._text_message_start()
                if evt.answer:
                    yield self._text_message_content(evt.answer)

            elif evt.event == "message_end":
                self._track_conversation(evt)
                self._end_message()
                if self._message_id:
                    yield self._text_message_end()
                self._finished = True
                yield self._run_finished()
                return

        if not self._finished:
            self._end_message()
            if self._message_id:
                yield self._text_message_end()
            yield self._run_finished()

    async def _handle_agent_thought(
        self, evt: DifyStreamEvent
    ) -> AsyncGenerator[BaseEvent, None]:
        position = evt.position or 0
        step_name = f"agent_thought_{position}"

        has_thought = bool(evt.thought)
        has_tool = bool(evt.tool)
        has_obs = bool(evt.observation)

        # Skip completely empty agent_thought (placeholder)
        if not has_thought and not has_tool and not has_obs:
            return

        yield self._step_started(step_name)

        if evt.thought:
            yield self._custom("agent_thought", {
                "position": position,
                "thought": evt.thought,
            })

        if evt.tool:
            self._current_tool_call_id = _new_id()
            yield self._tool_call_start(self._current_tool_call_id, evt.tool)
            if evt.tool_input:
                yield self._tool_call_args(self._current_tool_call_id, evt.tool_input)
            yield self._tool_call_end(self._current_tool_call_id)

        if evt.observation:
            yield self._custom("agent_observation", {
                "position": position,
                "tool": evt.tool,
                "observation": evt.observation,
            })

        yield self._step_finished(step_name)

    def _end_message(self):
        self._message_started = False
        self._current_step = None
        self._current_tool_call_id = None


class WorkflowTranslator(BaseTranslator):
    """Translates Dify Workflow app SSE events to AG-UI events."""

    def __init__(self, thread_id: str, run_id: str):
        super().__init__(thread_id, run_id)
        self._active_steps: dict[str, str] = {}
        self._agent_log_steps: dict[str, str] = {}  # log_id → label

    async def translate(
        self, events: AsyncGenerator[DifyStreamEvent, None]
    ) -> AsyncGenerator[BaseEvent, None]:
        run_started_yielded = False

        async for evt in events:
            if evt.event == "ping":
                continue

            if evt.event == "error":
                yield self._run_error(evt.message or "Unknown Dify error", evt.code)
                return

            if evt.event == "workflow_started":
                if not run_started_yielded:
                    run_started_yielded = True
                    self._message_id = _new_id()
                    yield self._run_started()
                    yield self._text_message_start()

            elif evt.event == "node_started":
                node_data = evt.data or {}
                node_id = node_data.get("node_id", _new_id())
                node_type = node_data.get("node_type", "unknown")
                node_name = node_data.get("node_name") or node_data.get("title") or node_id
                step_name = f"{node_type}:{node_name}"
                self._active_steps[node_id] = step_name
                yield self._step_started(step_name)

            elif evt.event == "agent_log":
                log_data = evt.data or {}
                log_id = log_data.get("id", _new_id())
                label = log_data.get("label", "agent")
                status = log_data.get("status", "")

                if status == "start":
                    # Track this as a sub-step
                    self._agent_log_steps[log_id] = label
                    yield self._step_started(f"agent:{label}")
                elif status in ("success", "error"):
                    step_name = self._agent_log_steps.pop(log_id, f"agent:{label}")
                    yield self._step_finished(step_name)

            elif evt.event == "text_chunk":
                if not self._message_id:
                    self._message_id = _new_id()
                    if not run_started_yielded:
                        run_started_yielded = True
                        yield self._run_started()
                    yield self._text_message_start()
                text = (evt.data or {}).get("text", "") or evt.extra.get("text", "") or evt.answer or ""
                if text:
                    yield self._text_message_content(text)

            elif evt.event == "node_finished":
                node_data = evt.data or {}
                node_id = node_data.get("node_id", "")
                node_name = node_data.get("node_name") or node_data.get("title") or node_id
                step_name = self._active_steps.pop(
                    node_id,
                    f"{node_data.get('node_type', 'unknown')}:{node_name}"
                )
                yield self._step_finished(step_name)

            elif evt.event == "workflow_finished":
                if self._message_id:
                    yield self._text_message_end()
                self._finished = True
                yield self._run_finished()
                return

        if not self._finished:
            if self._message_id:
                yield self._text_message_end()
            yield self._run_finished()


class CompletionTranslator(BaseTranslator):
    """Translates Dify Completion app SSE events to AG-UI events."""

    async def translate(
        self, events: AsyncGenerator[DifyStreamEvent, None]
    ) -> AsyncGenerator[BaseEvent, None]:
        yield self._run_started()

        async for evt in events:
            if evt.event == "ping":
                continue

            if evt.event == "error":
                yield self._run_error(evt.message or "Unknown Dify error", evt.code)
                return

            if evt.event == "message":
                if not self._message_started:
                    self._message_started = True
                    self._message_id = evt.message_id or evt.id or _new_id()
                    yield self._text_message_start()
                if evt.answer:
                    yield self._text_message_content(evt.answer)

            elif evt.event == "message_end":
                self._message_started = False
                if self._message_id:
                    yield self._text_message_end()
                self._finished = True
                yield self._run_finished()
                return

        if not self._finished:
            self._message_started = False
            if self._message_id:
                yield self._text_message_end()
            yield self._run_finished()
