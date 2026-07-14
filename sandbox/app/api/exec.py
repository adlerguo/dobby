import asyncio
import os
import resource
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from app.core.config import settings
from app.schemas import ExecIn, ExecOut

router = APIRouter(tags=["exec"])

ALLOWED_COMMANDS = {"python", "python3"}
EXEC_SEMAPHORE = asyncio.Semaphore(settings.max_concurrency)


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
    async with EXEC_SEMAPHORE:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=apply_resource_limits if os.name == "posix" else None,
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


def apply_resource_limits() -> None:
    memory_bytes = settings.memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_CPU, (settings.cpu_seconds, settings.cpu_seconds + 1))
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_NOFILE, (settings.max_open_files, settings.max_open_files))
    if hasattr(resource, "RLIMIT_NPROC"):
        resource.setrlimit(resource.RLIMIT_NPROC, (settings.max_processes, settings.max_processes))


def truncate(value: str) -> str:
    if len(value) <= settings.exec_output_limit:
        return value
    return value[: settings.exec_output_limit] + "\n[truncated]"
