"""Dify-specific type definitions and configuration models."""

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ConfiguredBaseModel(BaseModel):
    """Base model with camelCase alias serialization, matching ag_ui's pattern."""
    model_config = ConfigDict(
        extra="forbid",
        alias_generator=to_camel,
        populate_by_name=True,
        ser_json_by_alias=True,
    )


class DifyRequestBaseModel(BaseModel):
    """Base model for Dify API requests — uses snake_case, not camelCase."""
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
    )


class DifyAppType(str, Enum):
    """The four Dify application types."""
    CHAT = "chat"
    AGENT = "agent"
    WORKFLOW = "workflow"
    COMPLETION = "completion"


class DifyConfig(ConfiguredBaseModel):
    """Configuration for connecting to a Dify application."""
    api_key: str
    base_url: str = "https://api.dify.ai/v1"
    app_type: Optional[DifyAppType] = None
    user: str = "ag-ui-user"
    timeout: float = 120.0


class DifyFile(ConfiguredBaseModel):
    """A file attachment in Dify chat requests."""
    type: Literal["image", "document", "audio", "video"]
    transfer_method: Literal["remote_url", "local_file"]
    url: Optional[str] = None
    upload_file_id: Optional[str] = None


class DifyChatRequest(DifyRequestBaseModel):
    """Request body for POST /chat-messages."""
    query: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    response_mode: Literal["streaming", "blocking"] = "streaming"
    conversation_id: str = ""
    user: str = "ag-ui-user"
    files: List[DifyFile] = Field(default_factory=list)
    auto_generate_name: bool = True


class DifyWorkflowRequest(DifyRequestBaseModel):
    """Request body for POST /workflows/run."""
    inputs: Dict[str, Any] = Field(default_factory=dict)
    response_mode: Literal["streaming", "blocking"] = "streaming"
    user: str = "ag-ui-user"


class DifyCompletionRequest(DifyRequestBaseModel):
    """Request body for POST /completion-messages."""
    inputs: Dict[str, Any] = Field(default_factory=dict)
    response_mode: Literal["streaming", "blocking"] = "streaming"
    user: str = "ag-ui-user"
    files: List[DifyFile] = Field(default_factory=list)


class DifyParametersResponse(ConfiguredBaseModel):
    """Response from GET /parameters."""
    opening_statement: Optional[str] = None
    suggested_questions: Optional[List[str]] = None
    suggested_questions_after_answer: Optional[Dict[str, Any]] = None
    speech_to_text: Optional[Dict[str, Any]] = None
    text_to_speech: Optional[Dict[str, Any]] = None
    retriever_resource: Optional[Dict[str, Any]] = None
    file_upload: Optional[Dict[str, Any]] = None
    system_parameters: Optional[Dict[str, Any]] = None


class DifyMessageResponse(ConfiguredBaseModel):
    """A message in Dify conversation history."""
    id: str
    conversation_id: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    query: str
    answer: str
    message_files: List[Any] = Field(default_factory=list)
    feedback: Optional[Dict[str, Any]] = None
    retriever_resources: List[Any] = Field(default_factory=list)
    created_at: int


class DifyStreamEvent(BaseModel):
    """A single SSE event from Dify's streaming response.

    Uses snake_case field names matching Dify's JSON wire format.
    Allows extra fields to handle future Dify additions gracefully.
    """
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    event: str
    # Chat / Completion fields
    answer: Optional[str] = None
    message_id: Optional[str] = None
    conversation_id: Optional[str] = None
    task_id: Optional[str] = None
    id: Optional[str] = None
    created_at: Optional[int] = None
    # Agent fields
    thought: Optional[str] = None
    tool: Optional[str] = None
    tool_input: Optional[str] = None
    observation: Optional[str] = None
    position: Optional[int] = None
    # Workflow fields
    workflow_run_id: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    # Error fields
    message: Optional[str] = None
    code: Optional[str] = None
    status: Optional[int] = None
    # Metadata (message_end)
    metadata: Optional[Dict[str, Any]] = None
    # Audio
    audio: Optional[str] = None
    # Generic catch-all
    extra: Dict[str, Any] = Field(default_factory=dict)


class ConversationMapping(ConfiguredBaseModel):
    """Maps AG-UI thread IDs to Dify conversation IDs."""
    thread_id: str
    conversation_id: str
