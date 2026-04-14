from typing import Any

from pydantic import BaseModel, field_validator


class ChatMessage(BaseModel):
    role: str
    content: str

    @field_validator("content", mode="before")
    @classmethod
    def _coerce_content(cls, v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, str):
            return v
        if isinstance(v, list):
            parts: list[str] = []
            for item in v:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    if item.get("type") == "text" and isinstance(item.get("text"), str):
                        parts.append(item["text"])
            return "\n".join(parts)
        return str(v)


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    temperature: float = 1.0
    max_tokens: int | None = None
    top_p: float = 1.0
    stream: bool = False
    stop: str | list[str] | None = None


class Choice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: str | None


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage


class DeltaMessage(BaseModel):
    role: str | None = None
    content: str | None = None


class StreamChoice(BaseModel):
    index: int
    delta: DeltaMessage
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[StreamChoice]


class OpenAIModel(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str = "unchained"
    max_context_length: int = 4096


class OpenAIModelList(BaseModel):
    object: str = "list"
    data: list[OpenAIModel]
