"""Tests for DifyAgent."""

import unittest
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

from ag_ui.core import (
    AssistantMessage,
    BaseEvent,
    Context,
    CustomEvent,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    SystemMessage,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    Tool,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    UserMessage,
)

from ag_ui_dify.agent import DifyAgent
from ag_ui_dify.types import DifyAppType, DifyConfig, DifyStreamEvent


def make_run_input(
    messages: List[Any] = None,
    thread_id: str = "thread-1",
    run_id: str = "run-1",
    state: Any = None,
    tools: List = None,
    context: List = None,
    forwarded_props: Dict = None,
) -> RunAgentInput:
    return RunAgentInput(
        thread_id=thread_id,
        run_id=run_id,
        state=state,
        messages=messages or [UserMessage(id="u1", role="user", content="Hello")],
        tools=tools or [],
        context=context or [],
        forwarded_props=forwarded_props,
    )


class TestDifyAgentInit(unittest.TestCase):
    def test_create_agent(self):
        config = DifyConfig(api_key="test-key")
        agent = DifyAgent(config)
        self.assertIsNotNone(agent)

    def test_extract_query_from_messages(self):
        config = DifyConfig(api_key="test-key")
        agent = DifyAgent(config)
        input = make_run_input(
            messages=[
                UserMessage(id="u1", role="user", content="What is the weather?"),
                AssistantMessage(id="a1", role="assistant", content="Let me check."),
                UserMessage(id="u2", role="user", content="Actually, what about Tokyo?"),
            ]
        )
        query = agent._extract_query(input)
        self.assertEqual(query, "Actually, what about Tokyo?")

    def test_extract_query_empty(self):
        config = DifyConfig(api_key="test-key")
        agent = DifyAgent(config)
        input = make_run_input(messages=[
            SystemMessage(id="s1", role="system", content="You are helpful."),
        ])
        query = agent._extract_query(input)
        self.assertEqual(query, "")

    def test_build_inputs_from_state(self):
        config = DifyConfig(api_key="test-key")
        agent = DifyAgent(config)
        input = make_run_input(state={"city": "Tokyo", "language": "ja"})
        result = agent._build_inputs(input)
        self.assertEqual(result["city"], "Tokyo")
        self.assertEqual(result["language"], "ja")

    def test_build_inputs_from_context(self):
        config = DifyConfig(api_key="test-key")
        agent = DifyAgent(config)
        input = make_run_input(context=[
            Context(description="user_level", value="premium"),
            Context(description="region", value="APAC"),
        ])
        result = agent._build_inputs(input)
        self.assertEqual(result["user_level"], "premium")
        self.assertEqual(result["region"], "APAC")

    def test_build_inputs_from_forwarded_props(self):
        config = DifyConfig(api_key="test-key")
        agent = DifyAgent(config)
        input = make_run_input(forwarded_props={
            "apiKey": "app-xxx",
            "baseUrl": "https://custom.dify.io/v1",
            "inputs": {"extra_param": "value123"},
        })
        result = agent._build_inputs(input)
        self.assertEqual(result["extra_param"], "value123")

    def test_build_inputs_merged(self):
        config = DifyConfig(api_key="test-key")
        agent = DifyAgent(config)
        input = make_run_input(
            state={"from_state": "A"},
            context=[Context(description="from_context", value="B")],
            forwarded_props={"inputs": {"from_props": "C"}},
        )
        result = agent._build_inputs(input)
        self.assertEqual(result["from_state"], "A")
        self.assertEqual(result["from_context"], "B")
        self.assertEqual(result["from_props"], "C")

    def test_extract_files(self):
        config = DifyConfig(api_key="test-key")
        agent = DifyAgent(config)
        input = make_run_input(forwarded_props={
            "files": [
                {"type": "image", "transfer_method": "remote_url", "url": "https://x.com/a.png"},
            ]
        })
        files = agent._extract_files(input)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["url"], "https://x.com/a.png")

    def test_extract_files_empty(self):
        config = DifyConfig(api_key="test-key")
        agent = DifyAgent(config)
        input = make_run_input(forwarded_props={"apiKey": "test"})
        files = agent._extract_files(input)
        self.assertEqual(files, [])


class TestDifyAgentRun(unittest.IsolatedAsyncioTestCase):
    async def test_run_error_handling(self):
        """Test that exceptions during run produce RunErrorEvent."""
        config = DifyConfig(api_key="invalid", base_url="https://invalid.dify.ai/v1")
        agent = DifyAgent(config)
        input = make_run_input()

        events = []
        async for event in agent.run(input):
            events.append(event)

        # Should emit at least a RunErrorEvent
        error_events = [e for e in events if isinstance(e, RunErrorEvent)]
        self.assertGreaterEqual(len(error_events), 1)


if __name__ == "__main__":
    unittest.main()
