import ast
import csv
import io
import operator
from pathlib import Path
import re
import sqlite3
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.tool_policy import is_code_tool, is_code_tool_allowed
from app.models import Tool
from app.repositories import ToolRepository
from app.schemas import ToolCreate, ToolRunOut, ToolUpdate
from app.services.validation import detail_from_integrity_error, ensure_tenant_name_available


async def create_tool(db: AsyncSession, *, tenant_id: UUID, payload: ToolCreate) -> Tool:
    repo = ToolRepository(db, tenant_id)
    await ensure_tenant_name_available(
        db,
        model=Tool,
        tenant_id=tenant_id,
        name=payload.name,
        detail="tool_name_exists",
    )
    tool = Tool(
        tenant_id=tenant_id,
        name=payload.name,
        type=payload.type,
        schema=payload.tool_schema,
        config=payload.config,
        status="active",
    )
    try:
        await repo.add(tool)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError(detail_from_integrity_error(exc, "tool_create_conflict")) from exc
    await db.refresh(tool)
    return tool


async def update_tool(db: AsyncSession, *, tenant_id: UUID, tool_id: UUID, payload: ToolUpdate) -> Tool | None:
    repo = ToolRepository(db, tenant_id)
    values = payload.model_dump(exclude_unset=True)
    if payload.name is not None:
        await ensure_tenant_name_available(
            db,
            model=Tool,
            tenant_id=tenant_id,
            name=payload.name,
            detail="tool_name_exists",
            exclude_id=tool_id,
        )
    if "tool_schema" in values:
        values["schema"] = values.pop("tool_schema")
    tool = await repo.update_by_id(tool_id, values)
    if tool is None:
        return None
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError(detail_from_integrity_error(exc, "tool_update_conflict")) from exc
    await db.refresh(tool)
    return tool


async def disable_tool(db: AsyncSession, *, tenant_id: UUID, tool_id: UUID) -> bool:
    repo = ToolRepository(db, tenant_id)
    tool = await repo.update_by_id(tool_id, {"status": "disabled"})
    if tool is None:
        return False
    await db.commit()
    return True


async def run_tool(db: AsyncSession, *, tenant_id: UUID, tool_id: UUID, input: dict[str, Any]) -> ToolRunOut | None:
    repo = ToolRepository(db, tenant_id)
    tool = await repo.get_by_id(tool_id)
    if tool is None or tool.status != "active":
        return None

    if is_code_tool(tool) and not is_code_tool_allowed(tool):
        return ToolRunOut(
            tool_id=tool.id,
            type=tool.type,
            status="failed",
            output={"error": "forbidden", "detail": "代码类工具默认关闭，请在后端开启白名单后再执行。"},
        )

    if tool.type == "http":
        output = await run_http_tool(tool, input)
    elif tool.type == "code":
        output = await run_code_tool(tool, input)
    elif tool.type == "builtin":
        output = run_builtin_tool(tool, input)
    else:
        output = {"error": "unsupported_tool_type"}

    return ToolRunOut(tool_id=tool.id, type=tool.type, status="ok" if "error" not in output else "failed", output=output)


async def run_http_tool(tool: Tool, input: dict[str, Any]) -> dict[str, Any]:
    config = tool.config or {}
    url = input.get("url") or config.get("url")
    if not url:
        return {"error": "url_required"}

    method = str(input.get("method") or config.get("method") or "GET").upper()
    headers = dict(config.get("headers") or {})
    headers.update(input.get("headers") or {})
    params = input.get("params") or config.get("params")
    json_body = input.get("json", config.get("json"))
    timeout = float(config.get("timeout_seconds") or input.get("timeout_seconds") or 10)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method, url, headers=headers, params=params, json=json_body)
        text = response.text
        return {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": text[:12000],
        }
    except httpx.HTTPError as exc:
        return {"error": "http_tool_failed", "detail": str(exc)}


async def run_code_tool(tool: Tool, input: dict[str, Any]) -> dict[str, Any]:
    config = tool.config or {}
    code = input.get("code") or config.get("code")
    if not code:
        return {"error": "code_required"}

    payload = {
        "type": "python",
        "code": code,
        "timeout_seconds": input.get("timeout_seconds") or config.get("timeout_seconds") or 10,
    }
    try:
        async with httpx.AsyncClient(timeout=payload["timeout_seconds"] + 5) as client:
            response = await client.post(f"{settings.sandbox_base_url.rstrip('/')}/exec", json=payload)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        return {"error": "sandbox_call_failed", "detail": str(exc)}


def run_builtin_tool(tool: Tool, input: dict[str, Any]) -> dict[str, Any]:
    builtin = (tool.config or {}).get("builtin") or input.get("builtin") or tool.name
    if builtin == "echo":
        return {"value": input}
    if builtin == "calculator":
        expression = str(input.get("expression", ""))
        try:
            return {"value": safe_eval(expression)}
        except ValueError as exc:
            return {"error": "invalid_expression", "detail": str(exc)}
    if builtin == "nl2data":
        return run_nl2data_tool(tool, input)
    return {"error": "unknown_builtin"}


def safe_eval(expression: str) -> float:
    operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.USub: operator.neg,
    }

    def eval_node(node):
        if isinstance(node, ast.Expression):
            return eval_node(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.UnaryOp) and type(node.op) in operators:
            return operators[type(node.op)](eval_node(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in operators:
            return operators[type(node.op)](eval_node(node.left), eval_node(node.right))
        raise ValueError("unsupported_expression")

    return float(eval_node(ast.parse(expression, mode="eval")))


def run_nl2data_tool(tool: Tool, input: dict[str, Any]) -> dict[str, Any]:
    question = str(input.get("question") or input.get("query") or "")
    config = tool.config or {}
    db_path = resolve_demo_data_path(str(input.get("db_path") or config.get("db_path") or ""))
    if not db_path:
        return {"error": "db_path_required"}

    sql = str(input.get("sql") or "").strip()
    if not sql:
        sql = generate_demo_sql(question)

    try:
        sql = validate_select_sql(sql, allowed_tables=set(config.get("allowed_tables") or ["work_orders"]))
    except ValueError as exc:
        return {"error": "invalid_sql", "detail": str(exc), "sql": sql}

    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(sql)
            rows = [dict(row) for row in cursor.fetchall()]
            columns = [description[0] for description in cursor.description or []]
    except sqlite3.Error as exc:
        return {"error": "sql_execution_failed", "detail": str(exc), "sql": sql}

    return {
        "question": question,
        "sql": sql,
        "columns": columns,
        "rows": rows[:50],
        "row_count": len(rows),
        "data_csv": rows_to_csv(columns, rows[:50]),
        "summary": summarize_query_result(question, rows, columns),
    }


def resolve_demo_data_path(path: str) -> str:
    if not path:
        return ""
    if path.startswith("/"):
        return path
    app_root = Path(__file__).resolve().parents[1]
    return str(app_root / path)


def generate_demo_sql(question: str) -> str:
    normalized = question.lower()
    limit = top_n_from_question(question, default=10)
    if any(term in question for term in ("月趋势", "按月", "每月", "月份")):
        return (
            "SELECT strftime('%Y-%m', accept_time) AS month, COUNT(*) AS work_order_count "
            "FROM work_orders WHERE accept_time IS NOT NULL AND accept_time != '' "
            "GROUP BY month ORDER BY month LIMIT 20"
        )
    if any(term in question for term in ("街镇", "街道", "区域")):
        return (
            "SELECT street_town, COUNT(*) AS work_order_count "
            "FROM work_orders WHERE street_town IS NOT NULL AND street_town != '' "
            f"GROUP BY street_town ORDER BY work_order_count DESC LIMIT {limit}"
        )
    if any(term in question for term in ("部门", "主责", "承办")):
        return (
            "SELECT responsible_department_l3 AS responsible_department, COUNT(*) AS work_order_count "
            "FROM work_orders WHERE responsible_department_l3 IS NOT NULL AND responsible_department_l3 != '' "
            f"GROUP BY responsible_department ORDER BY work_order_count DESC LIMIT {limit}"
        )
    if any(term in question for term in ("小类", "子类", "类型", "分类", "案件")) and "总" not in question:
        return (
            "SELECT case_category_l2 AS case_category, COUNT(*) AS work_order_count "
            "FROM work_orders WHERE case_category_l2 IS NOT NULL AND case_category_l2 != '' "
            f"GROUP BY case_category ORDER BY work_order_count DESC LIMIT {limit}"
        )
    if "存电" in question:
        return (
            "SELECT has_stored_electricity, COUNT(*) AS work_order_count "
            "FROM work_orders WHERE has_stored_electricity IS NOT NULL AND has_stored_electricity != '' "
            f"GROUP BY has_stored_electricity ORDER BY work_order_count DESC LIMIT {limit}"
        )
    if any(term in normalized for term in ("count", "total")) or any(term in question for term in ("多少", "总量", "总数", "工单量")):
        return "SELECT COUNT(*) AS work_order_count FROM work_orders"
    return "SELECT task_id, accept_time, street_town, responsible_department_l3, problem_description FROM work_orders LIMIT 20"


def top_n_from_question(question: str, *, default: int) -> int:
    match = re.search(r"(?:前|top\s*)(\d{1,2})", question, flags=re.IGNORECASE)
    if not match:
        return default
    return max(1, min(int(match.group(1)), 50))


def validate_select_sql(sql: str, *, allowed_tables: set[str]) -> str:
    cleaned = sql.strip().rstrip(";")
    lowered = cleaned.lower()
    if not (lowered.startswith("select ") or lowered.startswith("with ")):
        raise ValueError("only_select_allowed")
    if ";" in cleaned:
        raise ValueError("multiple_statements_not_allowed")
    blocked = (" insert ", " update ", " delete ", " drop ", " alter ", " create ", " attach ", " detach ", " pragma ")
    padded = f" {lowered} "
    if any(keyword in padded for keyword in blocked):
        raise ValueError("write_or_admin_statement_not_allowed")

    tables = set(re.findall(r"\bfrom\s+([a-zA-Z_][\w]*)|\bjoin\s+([a-zA-Z_][\w]*)", lowered))
    flat_tables = {item for pair in tables for item in pair if item}
    if flat_tables and not flat_tables.issubset(allowed_tables):
        raise ValueError("table_not_allowed")
    if " limit " not in padded and "count(" not in lowered:
        cleaned = f"{cleaned} LIMIT 50"
    return cleaned


def rows_to_csv(columns: list[str], rows: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue().strip()


def summarize_query_result(question: str, rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "未查询到符合条件的数据。"
    if len(rows) == 1 and len(columns) == 1:
        return f"{question}：{rows[0][columns[0]]}。"
    top = rows[0]
    pairs = "，".join(f"{key}={value}" for key, value in top.items())
    return f"返回 {len(rows)} 行结果，排名第一/首行是：{pairs}。"
