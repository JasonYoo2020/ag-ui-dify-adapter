"""Comprehensive real integration tests for all Dify app types.

Requires environment variables for each app type. Tests are skipped
for any app type whose env var is not set.
"""

import os
import unittest

from ag_ui.core import (
    EventType,
    RunAgentInput,
    UserMessage,
)

from ag_ui_dify.agent import DifyAgent
from ag_ui_dify.types import DifyConfig, DifyAppType

# Integration tests are skipped unless env vars are set
_INTEGRATION_AVAILABLE = any(
    os.environ.get(k) for k in (
        "DIFY_AGENT_API_KEY", "DIFY_WORKFLOW_API_KEY",
        "DIFY_CHATBOT_API_KEY", "DIFY_COMPLETION_API_KEY",
    )
)

DIFY_BASE = os.environ.get("DIFY_BASE_URL", "http://localhost/v1")

# App configs — keys must be provided via environment variables.
# Skip tests if the corresponding env var is not set.
_AGENT_KEY = os.environ.get("DIFY_AGENT_API_KEY")
_WF_KEY = os.environ.get("DIFY_WORKFLOW_API_KEY")
_CHAT_KEY = os.environ.get("DIFY_CHATBOT_API_KEY")
_COMPLETION_KEY = os.environ.get("DIFY_COMPLETION_API_KEY")

APPS = {}
if _AGENT_KEY:
    APPS["agent"] = {
        "key": _AGENT_KEY,
        "type": DifyAppType.AGENT,
        "query": "请给我生成贵州茅台600519的公司一页纸",
    }
if _WF_KEY:
    APPS["workflow"] = {
        "key": _WF_KEY,
        "type": DifyAppType.WORKFLOW,
        "inputs": {"url": "https://www.moutai.com.cn/mtjt/index/index.html"},
    }
if _CHAT_KEY:
    APPS["chat"] = {
        "key": _CHAT_KEY,
        "type": DifyAppType.CHAT,
        "query": "请帮我生成一份项目启动会议的会议纪要模板",
    }
if _COMPLETION_KEY:
    APPS["completion"] = {
        "key": _COMPLETION_KEY,
        "type": DifyAppType.COMPLETION,
        "query": "convert code",
        "inputs": {"Target_code": "Python", "default_input": "print('hello')"},
    }


async def _collect(agen):
    results = []
    async for item in agen:
        results.append(item)
    return results


@unittest.skipUnless(
    _INTEGRATION_AVAILABLE,
    "Skipped: set DIFY_*_API_KEY env vars to run integration tests against real Dify",
)
class TestAllAppTypes(unittest.IsolatedAsyncioTestCase):

    async def _run_and_check(self, name: str, config: dict):
        print(f"\n{'='*60}")
        print(f"Testing {name.upper()} App")
        print(f"{'='*60}")

        agent = DifyAgent(DifyConfig(
            api_key=config["key"],
            base_url=DIFY_BASE,
            app_type=config["type"],
        ))

        if config["type"] == DifyAppType.WORKFLOW:
            input = RunAgentInput(
                thread_id=f"test-{name}-1",
                run_id=f"test-{name}-1",
                state=config.get("inputs", {}),
                messages=[UserMessage(id="u1", role="user", content="run workflow")],
                tools=[], context=[],
                forwarded_props={},
            )
        else:
            input = RunAgentInput(
                thread_id=f"test-{name}-1",
                run_id=f"test-{name}-1",
                state=None,
                messages=[UserMessage(id="u1", role="user", content=config["query"])],
                tools=[], context=[],
                forwarded_props={},
            )

        events = await _collect(agent.run(input))
        types = [e.type for e in events]

        print(f"Events: {len(events)}")
        print(f"Event types: {sorted(set(t.value for t in types))}")

        # Verify lifecycle
        self.assertIn(EventType.RUN_STARTED, types, f"[{name}] Missing RUN_STARTED")
        self.assertIn(EventType.RUN_FINISHED, types, f"[{name}] Missing RUN_FINISHED")
        self.assertNotIn(EventType.RUN_ERROR, types, f"[{name}] Got RUN_ERROR")

        # Verify app-type-specific events
        if config["type"] == DifyAppType.AGENT:
            has_tool = EventType.TOOL_CALL_START in types
            has_step = EventType.STEP_STARTED in types
            has_text = EventType.TEXT_MESSAGE_START in types
            print(f"Agent: tool_calls={has_tool}, steps={has_step}, text={has_text}")

        elif config["type"] == DifyAppType.WORKFLOW:
            has_step = EventType.STEP_STARTED in types
            has_text = EventType.TEXT_MESSAGE_START in types
            print(f"Workflow: steps={has_step}, text={has_text}")
            # Should have step events for nodes
            self.assertTrue(has_step, f"[{name}] No STEP events")
            # Count agent_log steps
            agent_steps = [e for e in events if e.type == EventType.STEP_STARTED
                           and e.step_name.startswith("agent:")]
            print(f"Agent log steps: {len(agent_steps)}")

        elif config["type"] == DifyAppType.CHAT:
            has_text = EventType.TEXT_MESSAGE_START in types
            print(f"Chat: text={has_text}")
            self.assertTrue(has_text, f"[{name}] No text message events")

        return events

    async def test_all_apps(self):
        for name, cfg in APPS.items():
            await self._run_and_check(name, cfg)


if __name__ == "__main__":
    unittest.main()
