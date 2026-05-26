"""Tests for DifyClient."""

import json
import unittest
from unittest.mock import AsyncMock, patch

from ag_ui_dify.dify_client import DifyClient
from ag_ui_dify.types import DifyAppType, DifyConfig, DifyStreamEvent


class TestDifyClient(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = DifyConfig(
            api_key="app-test",
            base_url="https://test.dify.ai/v1",
        )

    async def test_client_initialization(self):
        client = DifyClient(self.config)
        self.assertIsNotNone(client)
        await client.close()

    async def test_detect_app_type_from_config(self):
        config = DifyConfig(
            api_key="test",
            app_type=DifyAppType.AGENT,
        )
        client = DifyClient(config)
        app_type = await client.detect_app_type()
        self.assertEqual(app_type, DifyAppType.AGENT)
        await client.close()

    async def test_parse_sse_messages(self):
        """Test SSE parsing with multiple events."""
        import httpx

        response_data = (
            'data: {"event": "message", "answer": "Hello"}\n\n'
            'data: {"event": "message", "answer": " World"}\n\n'
            'data: {"event": "message_end", "message_id": "m1"}\n\n'
        )

        mock_response = httpx.Response(
            status_code=200,
            content=response_data.encode(),
            request=httpx.Request("POST", "https://test/v1/chat-messages"),
        )

        client = DifyClient(self.config)
        events = []
        async for evt in client._parse_sse_stream(mock_response):
            events.append(evt)

        self.assertEqual(len(events), 3)
        self.assertEqual(events[0].event, "message")
        self.assertEqual(events[0].answer, "Hello")
        self.assertEqual(events[1].answer, " World")
        self.assertEqual(events[2].event, "message_end")

    async def test_parse_sse_with_ping(self):
        """SSE parser should handle ping events."""
        import httpx

        response_data = (
            'data: {"event": "ping"}\n\n'
            'data: {"event": "message", "answer": "Hi"}\n\n'
            'data: {"event": "message_end"}\n\n'
        )

        mock_response = httpx.Response(
            status_code=200,
            content=response_data.encode(),
            request=httpx.Request("POST", "https://test/v1/chat-messages"),
        )

        client = DifyClient(self.config)
        events = []
        async for evt in client._parse_sse_stream(mock_response):
            events.append(evt)

        self.assertEqual(len(events), 3)
        self.assertEqual(events[0].event, "ping")

    async def test_parse_sse_with_empty_data(self):
        """SSE parser should skip empty data lines."""
        import httpx

        response_data = (
            '\n\n'
            'data: {"event": "message", "answer": "Hi"}\n\n'
            'data: [DONE]\n\n'
            '\n\n'
        )

        mock_response = httpx.Response(
            status_code=200,
            content=response_data.encode(),
            request=httpx.Request("POST", "https://test/v1/chat-messages"),
        )

        client = DifyClient(self.config)
        events = []
        async for evt in client._parse_sse_stream(mock_response):
            events.append(evt)

        # Should only get the message event, skip empty/DONE
        message_events = [e for e in events if e.event == "message"]
        self.assertEqual(len(message_events), 1)


if __name__ == "__main__":
    unittest.main()
