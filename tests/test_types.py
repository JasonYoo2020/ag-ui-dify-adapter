"""Tests for Dify-specific Pydantic type models."""

import unittest

from ag_ui_dify.types import (
    ConfiguredBaseModel,
    ConversationMapping,
    DifyAppType,
    DifyChatRequest,
    DifyCompletionRequest,
    DifyConfig,
    DifyFile,
    DifyStreamEvent,
    DifyWorkflowRequest,
)


class TestDifyAppType(unittest.TestCase):
    def test_enum_values(self):
        self.assertEqual(DifyAppType.CHAT, "chat")
        self.assertEqual(DifyAppType.AGENT, "agent")
        self.assertEqual(DifyAppType.WORKFLOW, "workflow")
        self.assertEqual(DifyAppType.COMPLETION, "completion")

    def test_from_string(self):
        self.assertEqual(DifyAppType("chat"), DifyAppType.CHAT)
        self.assertEqual(DifyAppType("agent"), DifyAppType.AGENT)


class TestDifyConfig(unittest.TestCase):
    def test_minimal_config(self):
        config = DifyConfig(api_key="app-test123")
        self.assertEqual(config.api_key, "app-test123")
        self.assertEqual(config.base_url, "https://api.dify.ai/v1")
        self.assertEqual(config.app_type, None)
        self.assertEqual(config.user, "ag-ui-user")

    def test_full_config(self):
        config = DifyConfig(
            api_key="app-full",
            base_url="https://custom.dify.io/v1",
            app_type=DifyAppType.AGENT,
            user="custom-user",
            timeout=60.0,
        )
        self.assertEqual(config.app_type, DifyAppType.AGENT)
        self.assertEqual(config.timeout, 60.0)

    def test_camel_case_serialization(self):
        config = DifyConfig(api_key="test-key")
        data = config.model_dump(by_alias=True)
        self.assertIn("apiKey", data)
        self.assertIn("baseUrl", data)
        self.assertIn("appType", data)

    def test_deserialize_from_camel_case(self):
        data = {"apiKey": "test-key", "baseUrl": "https://example.com/v1", "appType": "chat"}
        config = DifyConfig(**data)
        self.assertEqual(config.api_key, "test-key")
        self.assertEqual(config.base_url, "https://example.com/v1")
        self.assertEqual(config.app_type, DifyAppType.CHAT)


class TestDifyFile(unittest.TestCase):
    def test_remote_url_file(self):
        file = DifyFile(
            type="image",
            transfer_method="remote_url",
            url="https://example.com/img.png",
        )
        data = file.model_dump(by_alias=True)
        self.assertEqual(data["type"], "image")
        self.assertEqual(data["transferMethod"], "remote_url")

    def test_local_file(self):
        file = DifyFile(
            type="document",
            transfer_method="local_file",
            upload_file_id="file-uuid-123",
        )
        data = file.model_dump(by_alias=True)
        self.assertEqual(data["transferMethod"], "local_file")
        self.assertEqual(data["uploadFileId"], "file-uuid-123")


class TestDifyChatRequest(unittest.TestCase):
    def test_minimal_request(self):
        req = DifyChatRequest(query="Hello", user="user-1")
        data = req.model_dump()
        self.assertEqual(data["query"], "Hello")
        self.assertEqual(data["response_mode"], "streaming")
        self.assertEqual(data["conversation_id"], "")
        self.assertEqual(data["user"], "user-1")

    def test_with_all_fields(self):
        req = DifyChatRequest(
            query="Test query",
            inputs={"city": "Beijing"},
            response_mode="blocking",
            conversation_id="conv-123",
            user="user-2",
            files=[DifyFile(type="image", transfer_method="remote_url", url="https://x.com/a.png")],
            auto_generate_name=False,
        )
        data = req.model_dump()
        self.assertEqual(data["inputs"], {"city": "Beijing"})
        self.assertEqual(data["response_mode"], "blocking")
        self.assertEqual(data["auto_generate_name"], False)
        self.assertEqual(len(data["files"]), 1)


class TestDifyWorkflowRequest(unittest.TestCase):
    def test_minimal_request(self):
        req = DifyWorkflowRequest()
        data = req.model_dump()
        self.assertEqual(data["inputs"], {})
        self.assertEqual(data["response_mode"], "streaming")

    def test_with_inputs(self):
        req = DifyWorkflowRequest(inputs={"url": "https://example.com"})
        data = req.model_dump(by_alias=True)
        self.assertEqual(data["inputs"], {"url": "https://example.com"})


class TestDifyStreamEvent(unittest.TestCase):
    def test_chat_message_event(self):
        evt = DifyStreamEvent(
            event="message",
            answer="Hello, ",
            message_id="msg-1",
            conversation_id="conv-1",
            task_id="task-1",
        )
        self.assertEqual(evt.event, "message")
        self.assertEqual(evt.answer, "Hello, ")

    def test_agent_thought_event(self):
        evt = DifyStreamEvent(
            event="agent_thought",
            thought="I need to use a tool",
            tool="search",
            tool_input='{"query": "weather"}',
            observation="Found: sunny",
            position=1,
        )
        self.assertEqual(evt.tool, "search")
        self.assertEqual(evt.tool_input, '{"query": "weather"}')

    def test_workflow_event(self):
        evt = DifyStreamEvent(
            event="node_started",
            workflow_run_id="wf-1",
            data={"node_id": "node-1", "node_type": "llm", "node_name": "GPT-4"},
        )
        self.assertEqual(evt.workflow_run_id, "wf-1")
        self.assertEqual(evt.data["node_type"], "llm")

    def test_error_event(self):
        evt = DifyStreamEvent(
            event="error",
            message="Invalid API key",
            code="unauthorized",
            status=401,
        )
        self.assertEqual(evt.event, "error")
        self.assertEqual(evt.status, 401)

    def test_ping_event(self):
        evt = DifyStreamEvent(event="ping")
        self.assertEqual(evt.event, "ping")

    def test_extra_fields_captured(self):
        evt = DifyStreamEvent(event="message", answer="Hi", extra={"custom_field": 42})
        self.assertEqual(evt.extra["custom_field"], 42)


class TestConversationMapping(unittest.TestCase):
    def test_create_mapping(self):
        mapping = ConversationMapping(thread_id="thread-1", conversation_id="conv-1")
        data = mapping.model_dump(by_alias=True)
        self.assertEqual(data["threadId"], "thread-1")
        self.assertEqual(data["conversationId"], "conv-1")


if __name__ == "__main__":
    unittest.main()
