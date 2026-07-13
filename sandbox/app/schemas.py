from pydantic import BaseModel, Field


class ExecIn(BaseModel):
    model_config = {"extra": "forbid"}

    type: str = Field(pattern=r"^(python|command)$")
    code: str | None = None
    command: list[str] | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=30)


class ExecOut(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
