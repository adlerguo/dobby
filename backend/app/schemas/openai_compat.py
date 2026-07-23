from pydantic import BaseModel, Field


class ChatCompletionMessage(BaseModel):
    model_config = {"extra": "ignore"}

    role: str
    content: str


class ChatCompletionStreamOptions(BaseModel):
    model_config = {"extra": "ignore"}

    include_usage: bool = False


class ChatCompletionRequest(BaseModel):
    model_config = {"extra": "ignore"}

    model: str
    messages: list[ChatCompletionMessage] = Field(min_length=1)
    stream: bool = False
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    stream_options: ChatCompletionStreamOptions | None = None
