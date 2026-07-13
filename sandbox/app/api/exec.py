import asyncio
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from app.core.config import settings
from app.schemas import ExecIn, ExecOut

router = APIRouter(tags=["exec"])

ALLOWED_COMMANDS = {"python", "python3"}


@router.post("/exec", response_model=ExecOut, summary="Execute isolated task")
async def exec_task(payload: ExecIn) -> ExecOut:
    timeout = payload.timeout_seconds or settings.exec_timeout_seconds
    if payload.type == "python":
        if not payload.code:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="code_required")
        return await run_python(payload.code, timeout)

    if not payload.command:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="command_required")
    if payload.command[0] not in ALLOWED_COMMANDS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="command_not_allowed")
    return await run_process(payload.command, timeout)


async def run_python(code: str, timeout: int) -> ExecOut:
    with tempfile.TemporaryDirectory(prefix="sandbox-") as temp_dir:
        code_path = Path(temp_dir) / "main.py"
        code_path.write_text(code, encoding="utf-8")
        return await run_process(["python", str(code_path)], timeout)


async def run_process(command: list[str], timeout: int) -> ExecOut:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_raw, stderr_raw = await asyncio.wait_for(process.communicate(), timeout=timeout)
        timed_out = False
    except asyncio.TimeoutError:
        process.kill()
        stdout_raw, stderr_raw = await process.communicate()
        timed_out = True

    return ExecOut(
        exit_code=process.returncode if process.returncode is not None else -1,
        stdout=truncate(stdout_raw.decode("utf-8", errors="replace")),
        stderr=truncate(stderr_raw.decode("utf-8", errors="replace")),
        timed_out=timed_out,
    )


def truncate(value: str) -> str:
    if len(value) <= settings.exec_output_limit:
        return value
    return value[: settings.exec_output_limit] + "\n[truncated]"
