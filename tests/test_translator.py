"""Tests for event translators — Dify SSE → AG-UI event mapping."""

import unittest
from typing import List

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
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

from ag_ui_dify.event_translator import (
    AgentTranslator,
    ChatTranslator,
    CompletionTranslator,
    WorkflowTranslator,
)
from ag_ui_dify.types import DifyStreamEvent


def _to_dict(event: BaseEvent) -> dict:
    return event.model_dump(by_alias=True)


async def _collect(agen):
    """Collect all events from an async generator into a list."""
    results = []
    async for item in agen:
        results.append(item)
    return results


async def _make_event_stream(events: List[DifyStreamEvent]):
    """Create an async generator from a list of DifyStreamEvents."""
    for evt in events:
        yield evt


class TestChatTranslator(unittest.IsolatedAsyncioTestCase):
    def make_translator(self):
        return ChatTranslator(thread_id="t1", run_id="r1")

    async def test_basic_text_stream(self):
        events = [
            DifyStreamEvent(event="message", answer="Hello ", message_id="m1"),
            DifyStreamEvent(event="message", answer="World", message_id="m1"),
            DifyStreamEvent(event="message_end", message_id="m1", conversation_id="c1"),
        ]
        t = self.make_translator()
        results = await _collect(t.translate(_make_event_stream(events)))

        types = [e.type for e in results]
        self.assertIn("RUN_STARTED", types)
        self.assertIn("TEXT_MESSAGE_START", types)
        # Should have at least 2 content events
        content_events = [e for e in results if isinstance(e, TextMessageContentEvent)]
        self.assertEqual(len(content_events), 2)
        self.assertEqual(content_events[0].delta, "Hello ")
        self.assertEqual(content_events[1].delta, "World")
        self.assertIn("TEXT_MESSAGE_END", types)
        self.assertIn("RUN_FINISHED", types)
        self.assertEqual(t.conversation_id, "c1")

    async def test_single_message(self):
        events = [
            DifyStreamEvent(event="message", answer="Hi", message_id="m1"),
            DifyStreamEvent(event="message_end", message_id="m1"),
        ]
        t = self.make_translator()
        results = await _collect(t.translate(_make_event_stream(events)))
        content = [e for e in results if isinstance(e, TextMessageContentEvent)]
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0].delta, "Hi")

    async def test_message_file_event(self):
        events = [
            DifyStreamEvent(event="message", answer="Here is a file.", message_id="m1"),
            DifyStreamEvent(
                event="message_file",
                message_id="m1",
                extra={"file_url": "https://example.com/file.pdf"},
            ),
            DifyStreamEvent(event="message_end", message_id="m1"),
        ]
        t = self.make_translator()
        results = await _collect(t.translate(_make_event_stream(events)))
        custom_events = [e for e in results if isinstance(e, CustomEvent) and e.name == "message_file"]
        self.assertEqual(len(custom_events), 1)
        self.assertEqual(custom_events[0].value["data"]["file_url"], "https://example.com/file.pdf")

    async def test_error_event(self):
        events = [
            DifyStreamEvent(event="message", answer="Start", message_id="m1"),
            DifyStreamEvent(event="error", message="API error", code="500"),
        ]
        t = self.make_translator()
        results = await _collect(t.translate(_make_event_stream(events)))
        error_events = [e for e in results if isinstance(e, RunErrorEvent)]
        self.assertEqual(len(error_events), 1)
        self.assertEqual(error_events[0].message, "API error")
        # Should NOT have RUN_FINISHED after error
        finished = [e for e in results if isinstance(e, RunFinishedEvent)]
        self.assertEqual(len(finished), 0)

    async def test_ping_ignored(self):
        events = [
            DifyStreamEvent(event="ping"),
            DifyStreamEvent(event="message", answer="Hi", message_id="m1"),
            DifyStreamEvent(event="ping"),
            DifyStreamEvent(event="message_end", message_id="m1"),
        ]
        t = self.make_translator()
        results = await _collect(t.translate(_make_event_stream(events)))
        types = [e.type for e in results]
        self.assertNotIn("RAW", types)
        self.assertEqual(types.count("TEXT_MESSAGE_CONTENT"), 1)


class TestAgentTranslator(unittest.IsolatedAsyncioTestCase):
    def make_translator(self):
        return AgentTranslator(thread_id="t1", run_id="r1")

    async def test_agent_thought_with_tool(self):
        events = [
            DifyStreamEvent(
                event="agent_thought",
                thought="I need to search",
                tool="search",
                tool_input='{"query": "weather"}',
                observation="Sunny, 25C",
                position=1,
            ),
            DifyStreamEvent(event="agent_message", answer="The weather is sunny.", message_id="m1"),
            DifyStreamEvent(event="message_end", message_id="m1", conversation_id="c1"),
        ]
        t = self.make_translator()
        results = await _collect(t.translate(_make_event_stream(events)))

        types = [e.type for e in results]
        self.assertIn("RUN_STARTED", types)
        self.assertIn("STEP_STARTED", types)
        self.assertIn("STEP_FINISHED", types)
        self.assertIn("TOOL_CALL_START", types)
        self.assertIn("TOOL_CALL_ARGS", types)
        self.assertIn("TOOL_CALL_END", types)
        self.assertIn("TEXT_MESSAGE_START", types)
        self.assertIn("TEXT_MESSAGE_CONTENT", types)
        self.assertIn("TEXT_MESSAGE_END", types)
        self.assertIn("RUN_FINISHED", types)

        # Check tool call details
        tool_start = [e for e in results if isinstance(e, ToolCallStartEvent)][0]
        self.assertEqual(tool_start.tool_call_name, "search")

        tool_args = [e for e in results if isinstance(e, ToolCallArgsEvent)]
        self.assertTrue(any('weather' in a.delta for a in tool_args))

        # Check custom events
        customs = [e for e in results if isinstance(e, CustomEvent)]
        self.assertTrue(any(c.name == "agent_thought" for c in customs))
        self.assertTrue(any(c.name == "agent_observation" for c in customs))

    async def test_multiple_agent_thoughts(self):
        events = [
            DifyStreamEvent(
                event="agent_thought",
                thought="Step 1",
                tool="tool_a",
                tool_input="{}",
                observation="result_a",
                position=1,
            ),
            DifyStreamEvent(
                event="agent_thought",
                thought="Step 2",
                tool="tool_b",
                tool_input="{}",
                observation="result_b",
                position=2,
            ),
            DifyStreamEvent(event="agent_message", answer="Done.", message_id="m1"),
            DifyStreamEvent(event="message_end", message_id="m1"),
        ]
        t = self.make_translator()
        results = await _collect(t.translate(_make_event_stream(events)))

        steps_started = [e for e in results if isinstance(e, StepStartedEvent)]
        steps_finished = [e for e in results if isinstance(e, StepFinishedEvent)]
        self.assertEqual(len(steps_started), 2)
        self.assertEqual(len(steps_finished), 2)
        self.assertEqual(steps_started[0].step_name, "agent_thought_1")
        self.assertEqual(steps_started[1].step_name, "agent_thought_2")

    async def test_agent_thought_without_tool(self):
        """Agent thought with only reasoning, no tool call."""
        events = [
            DifyStreamEvent(
                event="agent_thought",
                thought="Let me think about this...",
                position=1,
            ),
            DifyStreamEvent(event="agent_message", answer="I think so.", message_id="m1"),
            DifyStreamEvent(event="message_end", message_id="m1"),
        ]
        t = self.make_translator()
        results = await _collect(t.translate(_make_event_stream(events)))

        tool_starts = [e for e in results if isinstance(e, ToolCallStartEvent)]
        self.assertEqual(len(tool_starts), 0)

        # Should still have thought as custom event
        thought_events = [e for e in results if isinstance(e, CustomEvent) and e.name == "agent_thought"]
        self.assertEqual(len(thought_events), 1)


class TestWorkflowTranslator(unittest.IsolatedAsyncioTestCase):
    def make_translator(self):
        return WorkflowTranslator(thread_id="t1", run_id="r1")

    async def test_workflow_with_nodes(self):
        events = [
            DifyStreamEvent(
                event="workflow_started",
                workflow_run_id="wf-1",
                data={"id": "wf-1"},
            ),
            DifyStreamEvent(
                event="node_started",
                data={"node_id": "n1", "node_type": "llm", "title": "GPT"},
            ),
            DifyStreamEvent(event="text_chunk", data={"text": "Processing..."}),
            DifyStreamEvent(
                event="node_finished",
                data={"node_id": "n1", "node_type": "llm", "title": "GPT", "status": "succeeded"},
            ),
            DifyStreamEvent(
                event="workflow_finished",
                workflow_run_id="wf-1",
                data={"status": "succeeded"},
            ),
        ]
        t = self.make_translator()
        results = await _collect(t.translate(_make_event_stream(events)))

        types = [e.type for e in results]
        self.assertIn("RUN_STARTED", types)
        self.assertIn("TEXT_MESSAGE_START", types)
        self.assertIn("STEP_STARTED", types)
        self.assertIn("TEXT_MESSAGE_CONTENT", types)
        self.assertIn("STEP_FINISHED", types)
        self.assertIn("TEXT_MESSAGE_END", types)
        self.assertIn("RUN_FINISHED", types)

        step_start = [e for e in results if isinstance(e, StepStartedEvent)][0]
        self.assertIn("llm", step_start.step_name)
        self.assertIn("GPT", step_start.step_name)

    async def test_workflow_with_error(self):
        events = [
            DifyStreamEvent(event="workflow_started", workflow_run_id="wf-1"),
            DifyStreamEvent(event="error", message="Node failed", code="NODE_ERROR"),
        ]
        t = self.make_translator()
        results = await _collect(t.translate(_make_event_stream(events)))
        error_events = [e for e in results if isinstance(e, RunErrorEvent)]
        self.assertEqual(len(error_events), 1)
        self.assertEqual(error_events[0].code, "NODE_ERROR")


class TestCompletionTranslator(unittest.IsolatedAsyncioTestCase):
    def make_translator(self):
        return CompletionTranslator(thread_id="t1", run_id="r1")

    async def test_basic_completion(self):
        events = [
            DifyStreamEvent(event="message", answer="Generated text.", message_id="m1"),
            DifyStreamEvent(event="message_end", message_id="m1"),
        ]
        t = self.make_translator()
        results = await _collect(t.translate(_make_event_stream(events)))

        types = [e.type for e in results]
        self.assertIn("RUN_STARTED", types)
        self.assertIn("TEXT_MESSAGE_START", types)
        self.assertIn("TEXT_MESSAGE_CONTENT", types)
        self.assertIn("TEXT_MESSAGE_END", types)
        self.assertIn("RUN_FINISHED", types)


class TestTranslatorEdgeCases(unittest.IsolatedAsyncioTestCase):
    async def test_empty_stream(self):
        t = ChatTranslator(thread_id="t1", run_id="r1")
        results = await _collect(t.translate(_make_event_stream([])))
        # Should still emit RUN_STARTED and RUN_FINISHED
        types = [e.type for e in results]
        self.assertIn("RUN_STARTED", types)
        self.assertIn("RUN_FINISHED", types)

    async def test_messages_without_message_id(self):
        """Dify may not always provide message_id."""
        events = [
            DifyStreamEvent(event="message", answer="Hello"),
            DifyStreamEvent(event="message_end"),
        ]
        t = ChatTranslator(thread_id="t1", run_id="r1")
        results = await _collect(t.translate(_make_event_stream(events)))
        # Should auto-generate message_id
        starts = [e for e in results if isinstance(e, TextMessageStartEvent)]
        self.assertEqual(len(starts), 1)
        self.assertTrue(starts[0].message_id)

    async def test_unicode_content(self):
        events = [
            DifyStreamEvent(event="message", answer="你好世界"),
            DifyStreamEvent(event="message", answer=" 🎉"),
            DifyStreamEvent(event="message_end"),
        ]
        t = ChatTranslator(thread_id="t1", run_id="r1")
        results = await _collect(t.translate(_make_event_stream(events)))
        contents = [e for e in results if isinstance(e, TextMessageContentEvent)]
        self.assertEqual(len(contents), 2)
        self.assertEqual(contents[0].delta, "你好世界")
        self.assertEqual(contents[1].delta, " 🎉")


if __name__ == "__main__":
    unittest.main()
