from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, get_current_auth
from app.core.database import get_db
from app.schemas.copilot import CopilotExecuteIn, CopilotExecuteOut, CopilotToolOut
from app.services.copilot_service import execute_copilot_tool, list_copilot_tools

router = APIRouter(tags=["copilot"])


@router.get("/copilot/tools", response_model=list[CopilotToolOut], summary="List copilot tools")
async def list_copilot_tools_api(
    auth: AuthContext = Depends(get_current_auth),
) -> list[CopilotToolOut]:
    return list_copilot_tools()


@router.post("/copilot/execute", response_model=CopilotExecuteOut, summary="Execute confirmed copilot tool")
async def execute_copilot_tool_api(
    payload: CopilotExecuteIn,
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> CopilotExecuteOut:
    return await execute_copilot_tool(db, auth=auth, payload=payload, request=request)
