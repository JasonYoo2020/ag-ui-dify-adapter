"""Dify SSE event → AG-UI event translators for each Dify app type.

Covers all 31+ Dify SSE event types and maps them to the full range of
AG-UI 33 event types, including REASONING, TOOL_CALL_RESULT, STATE/MESSAGES
snapshots, ACTIVITY, and RAW pass-through for unmapped events.
"""

import uuid
import re
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    EventType,
    MessagesSnapshotEvent,
    RawEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateSnapshotEvent,
    StepFinishedEvent,
    StepStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)

from .types import DifyStreamEvent

# Reasoning events may not exist in older ag-ui-protocol versions
try:
    from ag_ui.core import (
        ReasoningStartEvent,
        ReasoningMessageStartEvent,
        ReasoningMessageContentEvent,
        ReasoningMessageEndEvent,
        ReasoningEndEvent,
    )
    _HAS_REASONING = True
except ImportError:
    _HAS_REASONING = False

try:
    from ag_ui.core import ActivitySnapshotEvent, ActivityDeltaEvent
    _HAS_ACTIVITY = True
except ImportError:
    _HAS_ACTIVITY = False


def _new_id() -> str:
    return uuid.uuid4().hex


_RE_THINK_OPEN = re.compile(r'<think\b[^>]*>', re.IGNORECASE)
_RE_THINK_CLOSE = re.compile(r'</think>', re.IGNORECASE)


class BaseTranslator(ABC):
    """Base class for Dify-to-AG-UI event translators."""

    def __init__(self, thread_id: str, run_id: str):
        self.thread_id = thread_id
        self.run_id = run_id
        self._message_id: Optional[str] = None
        self._reasoning_message_id: Optional[str] = None
        self._message_started = False
        self._reasoning_started = False
        self._finished = False
        self._think_buffer = ""
        self._in_reasoning = False
        self.conversation_id: Optional[str] = None

    @abstractmethod
    async def translate(
        self, events: AsyncGenerator[DifyStreamEvent, None]
    ) -> AsyncGenerator[BaseEvent, None]:
        ...

    def _track_conversation(self, evt: DifyStreamEvent):
        if evt.conversation_id:
            self.conversation_id = evt.conversation_id

    # ── helper factories ──────────────────────────────────────────

    def _run_started(self, input=None) -> RunStartedEvent:
        return RunStartedEvent(
            type=EventType.RUN_STARTED,
            thread_id=self.thread_id,
            run_id=self.run_id,
            input=input,
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

    def _tool_call_result(self, tool_call_id: str, content: str) -> ToolCallResultEvent:
        return ToolCallResultEvent(
            type=EventType.TOOL_CALL_RESULT,
            message_id=self._message_id or _new_id(),
            tool_call_id=tool_call_id,
            content=content,
            role="tool",
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

    def _custom(self, name: str, value) -> CustomEvent:
        return CustomEvent(
            type=EventType.CUSTOM,
            name=name,
            value=value,
        )

    def _raw(self, event, source: str = "dify") -> RawEvent:
        return RawEvent(
            type=EventType.RAW,
            event=event,
            source=source,
        )

    def _state_snapshot(self, snapshot) -> StateSnapshotEvent:
        return StateSnapshotEvent(
            type=EventType.STATE_SNAPSHOT,
            snapshot=snapshot,
        )

    def _messages_snapshot(self, messages) -> MessagesSnapshotEvent:
        return MessagesSnapshotEvent(
            type=EventType.MESSAGES_SNAPSHOT,
            messages=messages,
        )

    # ── reasoning helpers ─────────────────────────────────────────

    def _ensure_reasoning_started(self, message_id: str = None):
        if not _HAS_REASONING:
            return None
        rid = message_id or self._reasoning_message_id or _new_id()
        if not self._reasoning_started:
            self._reasoning_message_id = rid
            self._reasoning_started = True
            return ReasoningStartEvent(
                type=EventType.REASONING_START,
                message_id=rid,
            )
        return None

    def _reasoning_message_start(self) -> Optional[BaseEvent]:
        if not _HAS_REASONING:
            return None
        return ReasoningMessageStartEvent(
            type=EventType.REASONING_MESSAGE_START,
            message_id=self._reasoning_message_id,
            role="reasoning",
        )

    def _reasoning_message_content(self, delta: str) -> Optional[BaseEvent]:
        if not _HAS_REASONING:
            return None
        return ReasoningMessageContentEvent(
            type=EventType.REASONING_MESSAGE_CONTENT,
            message_id=self._reasoning_message_id,
            delta=delta,
        )

    def _reasoning_message_end(self) -> Optional[BaseEvent]:
        if not _HAS_REASONING:
            return None
        return ReasoningMessageEndEvent(
            type=EventType.REASONING_MESSAGE_END,
            message_id=self._reasoning_message_id,
        )

    def _reasoning_end(self) -> Optional[BaseEvent]:
        if not _HAS_REASONING or not self._reasoning_started:
            return None
        self._reasoning_started = False
        self._reasoning_message_id = None
        return ReasoningEndEvent(
            type=EventType.REASONING_END,
            message_id=self._message_id or _new_id(),
        )

    # ── think-tag processing ──────────────────────────────────────

    async def _emit_text_with_reasoning(
        self, text: str
    ) -> AsyncGenerator[BaseEvent, None]:
        """Streaming <think> tag detection via state machine.

        Because <think> tags arrive token-by-token across SSE events,
        we buffer chunks and detect opening/closing boundaries."""
        if not _HAS_REASONING or ('<think' not in text and not self._in_reasoning
                                   and '<think' not in self._think_buffer):
            if text:
                yield self._text_message_content(text)
            return

        self._think_buffer += text

        while True:
            if self._in_reasoning:
                # Looking for </think> to end reasoning
                m = _RE_THINK_CLOSE.search(self._think_buffer)
                if m:
                    # Emit reasoning content before the close tag
                    reasoning_text = self._think_buffer[:m.start()]
                    if reasoning_text:
                        c = self._reasoning_message_content(reasoning_text)
                        if c:
                            yield c
                    # End reasoning message
                    me = self._reasoning_message_end()
                    if me:
                        yield me
                    self._in_reasoning = False
                    # Continue processing the rest
                    self._think_buffer = self._think_buffer[m.end():]
                    continue
                else:
                    # No close tag yet — emit partial reasoning content
                    # but keep some buffer to avoid splitting </think>
                    safe_len = max(0, len(self._think_buffer) - 8)  # keep last "</think>" chars
                    if safe_len > 0:
                        c = self._reasoning_message_content(self._think_buffer[:safe_len])
                        if c:
                            yield c
                        self._think_buffer = self._think_buffer[safe_len:]
                    break
            else:
                # Looking for <think> to start reasoning
                m_open = _RE_THINK_OPEN.search(self._think_buffer)
                if m_open:
                    # Emit text before the open tag
                    pre_text = self._think_buffer[:m_open.start()]
                    if pre_text:
                        yield self._text_message_content(pre_text)
                    # Start reasoning
                    re_evt = self._ensure_reasoning_started()
                    if re_evt:
                        yield re_evt
                    ms = self._reasoning_message_start()
                    if ms:
                        yield ms
                    self._in_reasoning = True
                    self._think_buffer = self._think_buffer[m_open.end():]
                    continue
                else:
                    # No open tag — but we might have partial "<thin" at the end
                    # Keep the last few chars that could be a partial tag
                    safe_len = max(0, len(self._think_buffer) - 7)
                    if safe_len > 0 and not any(
                        self._think_buffer.rfind(t) >= max(0, len(self._think_buffer) - 10)
                        for t in ('<think', '<thin', '<thi', '<th', '<t', '<')
                    ):
                        yield self._text_message_content(self._think_buffer[:safe_len])
                        self._think_buffer = self._think_buffer[safe_len:]
                    break

    async def _flush_reasoning(self) -> AsyncGenerator[BaseEvent, None]:
        if self._reasoning_started:
            e = self._reasoning_end()
            if e:
                yield e


class BaseTextTranslator(BaseTranslator):
    """Shared logic for Chat/Agent/Completion translators."""

    def __init__(self, thread_id: str, run_id: str):
        super().__init__(thread_id, run_id)

    async def _handle_message_end(
        self, evt: DifyStreamEvent, end_reasoning: bool = True
    ) -> AsyncGenerator[BaseEvent, None]:
        self._track_conversation(evt)
        if end_reasoning:
            async for e in self._flush_reasoning():
                yield e
        self._message_started = False
        if self._message_id:
            yield self._text_message_end()
        self._finished = True
        yield self._run_finished()


class ChatTranslator(BaseTextTranslator):
    """Translates Dify Chat app SSE events to AG-UI events."""

    async def translate(
        self, events: AsyncGenerator[DifyStreamEvent, None]
    ) -> AsyncGenerator[BaseEvent, None]:
        yield self._run_started()

        async for evt in events:
            if evt.event == "ping":
                continue

            if evt.event == "error":
                yield self._run_error(
                    evt.message or evt.extra.get("message", "Unknown Dify error"),
                    evt.code,
                )
                return

            if evt.event == "message":
                if not self._message_started:
                    self._message_started = True
                    self._message_id = evt.message_id or evt.id or _new_id()
                    yield self._text_message_start()
                if evt.answer:
                    async for e in self._emit_text_with_reasoning(evt.answer):
                        yield e

            elif evt.event == "message_replace":
                yield self._custom("message_replace", {
                    "answer": evt.answer,
                    "reason": evt.extra.get("reason"),
                })

            elif evt.event == "message_file":
                yield self._custom("message_file", {
                    "message_id": evt.message_id,
                    "data": evt.extra,
                })

            elif evt.event == "message_end":
                async for e in self._handle_message_end(evt):
                    yield e
                return

            elif evt.event == "tts_message":
                if evt.audio:
                    yield self._custom("tts_message", {"audio": evt.audio})

            elif evt.event == "tts_message_end":
                yield self._custom("tts_message_end", {})

            else:
                # Unhandled event → RAW pass-through
                yield self._raw(evt.model_dump(exclude_none=True))

        if not self._finished:
            async for e in self._flush_reasoning():
                yield e
            self._message_started = False
            if self._message_id:
                yield self._text_message_end()
            yield self._run_finished()


class AgentTranslator(BaseTextTranslator):
    """Translates Dify Agent app SSE events to AG-UI events."""

    def __init__(self, thread_id: str, run_id: str):
        super().__init__(thread_id, run_id)
        self._current_tool_call_id: Optional[str] = None

    async def translate(
        self, events: AsyncGenerator[DifyStreamEvent, None]
    ) -> AsyncGenerator[BaseEvent, None]:
        yield self._run_started()

        async for evt in events:
            if evt.event == "ping":
                continue

            if evt.event == "error":
                yield self._run_error(
                    evt.message or evt.extra.get("message", "Unknown Dify error"),
                    evt.code,
                )
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
                    async for e in self._emit_text_with_reasoning(evt.answer):
                        yield e

            elif evt.event == "message_replace":
                yield self._custom("message_replace", {
                    "answer": evt.answer,
                    "reason": evt.extra.get("reason"),
                })

            elif evt.event == "message_file":
                yield self._custom("message_file", {
                    "message_id": evt.message_id,
                    "data": evt.extra,
                })

            elif evt.event == "message_end":
                async for e in self._handle_message_end(evt):
                    yield e
                return

            else:
                yield self._raw(evt.model_dump(exclude_none=True))

        if not self._finished:
            async for e in self._flush_reasoning():
                yield e
            self._message_started = False
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

        if not has_thought and not has_tool and not has_obs:
            return

        yield self._step_started(step_name)

        # Process thought content — may contain <think> tags
        if evt.thought:
            if _HAS_REASONING and '<think' in (evt.thought or ""):
                # Thought comes as a complete block — parse <think> tags
                m_open = _RE_THINK_OPEN.search(evt.thought)
                if m_open:
                    pre = evt.thought[:m_open.start()]
                    if pre:
                        yield self._custom("agent_thought", {"position": position, "thought": pre})
                    re_evt = self._ensure_reasoning_started()
                    if re_evt:
                        yield re_evt
                    ms = self._reasoning_message_start()
                    if ms:
                        yield ms
                    inner = evt.thought[m_open.end():]
                    m_close = _RE_THINK_CLOSE.search(inner)
                    if m_close:
                        c = self._reasoning_message_content(inner[:m_close.start()])
                        if c:
                            yield c
                        me = self._reasoning_message_end()
                        if me:
                            yield me
                        remaining = inner[m_close.end():]
                        if remaining:
                            yield self._custom("agent_thought", {"position": position, "thought": remaining})
                    else:
                        c = self._reasoning_message_content(inner)
                        if c:
                            yield c
                        me = self._reasoning_message_end()
                        if me:
                            yield me
                else:
                    yield self._custom("agent_thought", {"position": position, "thought": evt.thought})
            else:
                yield self._custom("agent_thought", {
                    "position": position,
                    "thought": evt.thought,
                })

        # Tool calls
        if evt.tool:
            self._current_tool_call_id = _new_id()
            yield self._tool_call_start(self._current_tool_call_id, evt.tool)
            if evt.tool_input:
                yield self._tool_call_args(self._current_tool_call_id, evt.tool_input)
            yield self._tool_call_end(self._current_tool_call_id)

        # Tool observation → TOOL_CALL_RESULT instead of CUSTOM
        if evt.observation:
            if self._current_tool_call_id:
                yield self._tool_call_result(
                    self._current_tool_call_id, evt.observation
                )
            else:
                yield self._custom("agent_observation", {
                    "position": position,
                    "tool": evt.tool,
                    "observation": evt.observation,
                })

        yield self._step_finished(step_name)


class WorkflowTranslator(BaseTextTranslator):
    """Translates Dify Workflow app SSE events to AG-UI events."""

    def __init__(self, thread_id: str, run_id: str):
        super().__init__(thread_id, run_id)
        self._active_steps: dict[str, str] = {}
        self._agent_log_steps: dict[str, str] = {}

    async def translate(
        self, events: AsyncGenerator[DifyStreamEvent, None]
    ) -> AsyncGenerator[BaseEvent, None]:
        run_started_yielded = False

        async for evt in events:
            if evt.event == "ping":
                continue

            if evt.event == "error":
                yield self._run_error(
                    evt.message or evt.extra.get("message", "Unknown Dify error"),
                    evt.code,
                )
                return

            if evt.event == "workflow_started":
                if not run_started_yielded:
                    run_started_yielded = True
                    self._message_id = _new_id()
                    yield self._run_started()
                    yield self._text_message_start()

            elif evt.event == "workflow_paused":
                yield self._custom("workflow_paused", evt.data or {})
                if self._message_id:
                    yield self._text_message_end()
                self._finished = True
                yield self._run_finished()
                return

            elif evt.event == "node_started":
                node_data = evt.data or {}
                node_id = node_data.get("node_id", _new_id())
                node_type = node_data.get("node_type", "unknown")
                node_name = node_data.get("node_name") or node_data.get("title") or node_id
                step_name = f"{node_type}:{node_name}"
                self._active_steps[node_id] = step_name
                yield self._step_started(step_name)

            elif evt.event == "node_retry":
                node_data = evt.data or {}
                node_id = node_data.get("node_id", "")
                node_type = node_data.get("node_type", "unknown")
                node_name = node_data.get("node_name") or node_data.get("title") or node_id
                retry_index = node_data.get("retry_index", 1)
                step_name = f"{node_type}:{node_name} (retry #{retry_index})"
                self._active_steps[node_id] = step_name
                yield self._step_started(step_name)

            elif evt.event == "agent_log":
                log_data = evt.data or {}
                log_id = log_data.get("id", _new_id())
                label = log_data.get("label", "agent")
                status = log_data.get("status", "")

                if status == "start":
                    self._agent_log_steps[log_id] = label
                    yield self._step_started(f"agent:{label}")
                elif status in ("success", "error"):
                    step_name = self._agent_log_steps.pop(log_id, f"agent:{label}")
                    yield self._step_finished(step_name)

            elif evt.event in ("iteration_started", "loop_started"):
                data = evt.data or {}
                node_id = data.get("node_id", _new_id())
                node_type = data.get("node_type", evt.event.split("_")[0])
                title = data.get("title", node_id)
                step_name = f"{node_type}_iter:{title}"
                self._active_steps[node_id] = step_name
                yield self._step_started(step_name)

            elif evt.event in ("iteration_completed", "loop_completed"):
                data = evt.data or {}
                node_id = data.get("node_id", "")
                step_name = self._active_steps.pop(
                    node_id, f"{data.get('node_type','iteration')}:{data.get('title',node_id)}"
                )
                yield self._step_finished(step_name)

            elif evt.event in ("iteration_next", "loop_next"):
                # Sub-iteration boundary — emit as RAW for visibility
                yield self._raw(evt.model_dump(exclude_none=True))

            elif evt.event == "text_chunk":
                if not self._message_id:
                    self._message_id = _new_id()
                    if not run_started_yielded:
                        run_started_yielded = True
                        yield self._run_started()
                    yield self._text_message_start()
                text = (evt.data or {}).get("text", "") or evt.extra.get("text", "") or evt.answer or ""
                if text:
                    async for e in self._emit_text_with_reasoning(text):
                        yield e

            elif evt.event == "text_replace":
                data = evt.data or {}
                text = data.get("text", "")
                if text:
                    yield self._custom("text_replace", {"text": text})

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
                async for e in self._flush_reasoning():
                    yield e
                if self._message_id:
                    yield self._text_message_end()
                self._finished = True
                yield self._run_finished()
                return

            elif evt.event == "human_input_required":
                yield self._custom("human_input_required", evt.data or {})

            elif evt.event in ("human_input_form_filled", "human_input_form_timeout"):
                yield self._custom(evt.event, evt.data or {})

            else:
                yield self._raw(evt.model_dump(exclude_none=True))

        if not self._finished:
            async for e in self._flush_reasoning():
                yield e
            if self._message_id:
                yield self._text_message_end()
            yield self._run_finished()


class CompletionTranslator(BaseTextTranslator):
    """Translates Dify Completion app SSE events to AG-UI events."""

    async def translate(
        self, events: AsyncGenerator[DifyStreamEvent, None]
    ) -> AsyncGenerator[BaseEvent, None]:
        yield self._run_started()

        async for evt in events:
            if evt.event == "ping":
                continue

            if evt.event == "error":
                yield self._run_error(
                    evt.message or evt.extra.get("message", "Unknown Dify error"),
                    evt.code,
                )
                return

            if evt.event == "message":
                if not self._message_started:
                    self._message_started = True
                    self._message_id = evt.message_id or evt.id or _new_id()
                    yield self._text_message_start()
                if evt.answer:
                    async for e in self._emit_text_with_reasoning(evt.answer):
                        yield e

            elif evt.event == "message_end":
                async for e in self._handle_message_end(evt):
                    yield e
                return

            elif evt.event == "message_file":
                yield self._custom("message_file", {
                    "message_id": evt.message_id,
                    "data": evt.extra,
                })

            elif evt.event == "tts_message":
                if evt.audio:
                    yield self._custom("tts_message", {"audio": evt.audio})

            elif evt.event == "tts_message_end":
                yield self._custom("tts_message_end", {})

            else:
                yield self._raw(evt.model_dump(exclude_none=True))

        if not self._finished:
            async for e in self._flush_reasoning():
                yield e
            self._message_started = False
            if self._message_id:
                yield self._text_message_end()
            yield self._run_finished()
