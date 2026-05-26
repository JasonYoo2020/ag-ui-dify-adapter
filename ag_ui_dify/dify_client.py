"""Async HTTP client for Dify REST API with SSE streaming support."""

import json
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from .types import (
    DifyAppType,
    DifyChatRequest,
    DifyCompletionRequest,
    DifyConfig,
    DifyMessageResponse,
    DifyParametersResponse,
    DifyStreamEvent,
    DifyWorkflowRequest,
)


class DifyClient:
    """Async HTTP client for all Dify API endpoints.

    Handles SSE stream parsing and app type auto-detection.
    """

    def __init__(self, config: DifyConfig):
        self._config = config
        self._client: Optional[httpx.AsyncClient] = None
        self._detected_app_type: Optional[DifyAppType] = config.app_type

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._config.base_url,
                headers={
                    "Authorization": f"Bearer {self._config.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(self._config.timeout),
            )
        return self._client

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _clean_request_data(self, data: dict) -> dict:
        """Remove empty optional fields from request data."""
        if isinstance(data.get("files"), list) and len(data["files"]) == 0:
            data.pop("files", None)
        if data.get("conversation_id") == "":
            data.pop("conversation_id", None)
        return data

    async def _parse_sse_stream(
        self, response: httpx.Response
    ) -> AsyncGenerator[DifyStreamEvent, None]:
        """Parse an SSE stream response into DifyStreamEvent objects."""
        buffer = ""
        async for chunk in response.aiter_bytes():
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n\n" in buffer:
                message, buffer = buffer.split("\n\n", 1)
                for line in message.split("\n"):
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload.strip() in ("", "[DONE]"):
                        continue
                    try:
                        data = json.loads(payload)
                        yield DifyStreamEvent(**data)
                    except Exception:
                        continue

    async def detect_app_type(self) -> DifyAppType:
        """Auto-detect the Dify app type via the /parameters endpoint."""
        if self._detected_app_type is not None:
            return self._detected_app_type

        client = await self._get_client()
        try:
            resp = await client.get("/parameters")
            resp.raise_for_status()
            data = resp.json()
            params = DifyParametersResponse(**data)
            mode = (params.system_parameters or {}).get("mode", "chat")
            self._detected_app_type = DifyAppType(mode)
        except Exception:
            try:
                resp = await client.post("/chat-messages", json={
                    "query": "__test__",
                    "response_mode": "blocking",
                    "user": self._config.user,
                })
                if resp.status_code != 400:
                    self._detected_app_type = DifyAppType.CHAT
                else:
                    self._detected_app_type = DifyAppType.WORKFLOW
            except Exception:
                self._detected_app_type = DifyAppType.CHAT

        return self._detected_app_type

    async def get_parameters(self) -> DifyParametersResponse:
        """Get app parameters including input variable definitions."""
        client = await self._get_client()
        resp = await client.get("/parameters")
        resp.raise_for_status()
        return DifyParametersResponse(**resp.json())

    async def stream_chat(
        self,
        query: str,
        inputs: Optional[Dict[str, Any]] = None,
        conversation_id: str = "",
        files: Optional[List[Dict[str, Any]]] = None,
        user: Optional[str] = None,
    ) -> AsyncGenerator[DifyStreamEvent, None]:
        """Stream chat messages (Chat / Agent app types).

        Yields DifyStreamEvent for each SSE event.
        """
        request = DifyChatRequest(
            query=query,
            inputs=inputs or {},
            conversation_id=conversation_id,
            user=user or self._config.user,
            files=files or [],
        )

        client = await self._get_client()
        async with client.stream(
            "POST",
            "/chat-messages",
            json=self._clean_request_data(request.model_dump(exclude_none=True)),
        ) as response:
            response.raise_for_status()
            async for event in self._parse_sse_stream(response):
                yield event

    async def stream_workflow(
        self,
        inputs: Optional[Dict[str, Any]] = None,
        user: Optional[str] = None,
    ) -> AsyncGenerator[DifyStreamEvent, None]:
        """Stream workflow execution (Workflow app type)."""
        request = DifyWorkflowRequest(
            inputs=inputs or {},
            user=user or self._config.user,
        )

        client = await self._get_client()
        async with client.stream(
            "POST",
            "/workflows/run",
            json=self._clean_request_data(request.model_dump(exclude_none=True)),
        ) as response:
            response.raise_for_status()
            async for event in self._parse_sse_stream(response):
                yield event

    async def stream_completion(
        self,
        inputs: Optional[Dict[str, Any]] = None,
        files: Optional[List[Dict[str, Any]]] = None,
        user: Optional[str] = None,
    ) -> AsyncGenerator[DifyStreamEvent, None]:
        """Stream text completion (Completion app type)."""
        request = DifyCompletionRequest(
            inputs=inputs or {},
            user=user or self._config.user,
            files=files or [],
        )

        client = await self._get_client()
        async with client.stream(
            "POST",
            "/completion-messages",
            json=self._clean_request_data(request.model_dump(exclude_none=True)),
        ) as response:
            response.raise_for_status()
            async for event in self._parse_sse_stream(response):
                yield event

    async def stop_chat(self, task_id: str, user: Optional[str] = None) -> Dict[str, Any]:
        """Stop an in-progress chat message generation."""
        client = await self._get_client()
        resp = await client.post(
            f"/chat-messages/{task_id}/stop",
            json={"user": user or self._config.user},
        )
        resp.raise_for_status()
        return resp.json()

    async def get_messages(
        self,
        conversation_id: str,
        user: str,
        first_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[DifyMessageResponse]:
        """Get conversation message history."""
        client = await self._get_client()
        params = {
            "conversation_id": conversation_id,
            "user": user,
            "limit": limit,
        }
        if first_id:
            params["first_id"] = first_id

        resp = await client.get("/messages", params=params)
        resp.raise_for_status()
        data = resp.json()
        return [DifyMessageResponse(**msg) for msg in data.get("data", [])]

    async def get_conversations(
        self,
        user: str,
        last_id: Optional[str] = None,
        limit: int = 20,
        sort_by: str = "-updated_at",
    ) -> List[Dict[str, Any]]:
        """Get list of conversations for a user."""
        client = await self._get_client()
        params = {"user": user, "limit": limit, "sort_by": sort_by}
        if last_id:
            params["last_id"] = last_id

        resp = await client.get("/conversations", params=params)
        resp.raise_for_status()
        return resp.json().get("data", [])

    async def upload_file(
        self, file_path: str, user: str
    ) -> Dict[str, Any]:
        """Upload a file to Dify for use in chat messages."""
        client = await self._get_client()
        with open(file_path, "rb") as f:
            files = {"file": f}
            data = {"user": user}
            # Use a separate client without the JSON content-type header
            async with httpx.AsyncClient(
                base_url=self._config.base_url,
                headers={"Authorization": f"Bearer {self._config.api_key}"},
                timeout=httpx.Timeout(self._config.timeout),
            ) as upload_client:
                resp = await upload_client.post(
                    "/files/upload",
                    files=files,
                    data=data,
                )
        resp.raise_for_status()
        return resp.json()
