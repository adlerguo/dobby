import ast
import csv
import json
import ipaddress
import io
import operator
from pathlib import Path
import re
import sqlite3
import socket
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
import sqlglot
from sqlglot import exp
from sqlglot.tokens import TokenType, Tokenizer
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.maas_auth import maas_service_headers
from app.core.tool_policy import is_code_tool, is_code_tool_allowed
from app.models import Agent, AgentTool, Model, ModelChannel, Tool
from app.repositories import ToolRepository
from app.schemas import ToolCreate, ToolDraftIn, ToolDraftOut, ToolRunOut, ToolUpdate
from app.services.validation import (
    detail_from_integrity_error,
    ensure_tenant_name_available,
)


async def create_tool(
    db: AsyncSession, *, tenant_id: UUID, payload: ToolCreate
) -> Tool:
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
        raise ValueError(
            detail_from_integrity_error(exc, "tool_create_conflict")
        ) from exc
    await db.refresh(tool)
    return tool


async def update_tool(
    db: AsyncSession, *, tenant_id: UUID, tool_id: UUID, payload: ToolUpdate
) -> Tool | None:
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
        raise ValueError(
            detail_from_integrity_error(exc, "tool_update_conflict")
        ) from exc
    await db.refresh(tool)
    return tool


async def disable_tool(db: AsyncSession, *, tenant_id: UUID, tool_id: UUID) -> bool:
    repo = ToolRepository(db, tenant_id)
    tool = await repo.update_by_id(tool_id, {"status": "disabled"})
    if tool is None:
        return False
    await db.commit()
    return True


async def bind_tool_to_agents(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    tool_id: UUID,
    agent_ids: list[UUID],
) -> list[UUID] | None:
    repo = ToolRepository(db, tenant_id)
    tool = await repo.get_by_id(tool_id)
    if tool is None:
        return None

    unique_agent_ids = list(dict.fromkeys(agent_ids))
    if unique_agent_ids:
        result = await db.execute(
            select(Agent.id).where(
                Agent.tenant_id == tenant_id,
                Agent.id.in_(unique_agent_ids),
                Agent.status.is_distinct_from("archived"),
            )
        )
        found = set(result.scalars().all())
        missing = [
            str(agent_id) for agent_id in unique_agent_ids if agent_id not in found
        ]
        if missing:
            raise ValueError(f"agent_not_found:{','.join(missing)}")

    await db.execute(delete(AgentTool).where(AgentTool.tool_id == tool_id))
    for agent_id in unique_agent_ids:
        db.add(AgentTool(agent_id=agent_id, tool_id=tool_id))
    await db.commit()
    return unique_agent_ids


async def run_tool(
    db: AsyncSession, *, tenant_id: UUID, tool_id: UUID, input: dict[str, Any]
) -> ToolRunOut | None:
    repo = ToolRepository(db, tenant_id)
    tool = await repo.get_by_id(tool_id)
    if tool is None or tool.status != "active":
        return None

    if is_code_tool(tool) and not is_code_tool_allowed(tool):
        return ToolRunOut(
            tool_id=tool.id,
            type=tool.type,
            status="failed",
            output={
                "error": "forbidden",
                "detail": "代码类工具默认关闭，请在后端开启白名单后再执行。",
            },
        )

    if tool.type == "http":
        output = await run_http_tool(tool, input)
    elif tool.type == "code":
        output = await run_code_tool(tool, input)
    elif tool.type == "builtin":
        output = run_builtin_tool(tool, input)
    elif tool.type == "mcp":
        output = {"error": "coming_soon", "detail": "外部 MCP 工具执行即将支持。"}
    else:
        output = {"error": "unsupported_tool_type"}

    return ToolRunOut(
        tool_id=tool.id,
        type=tool.type,
        status="ok" if "error" not in output else "failed",
        output=output,
    )


async def draft_tool(
    db: AsyncSession, *, tenant_id: UUID, payload: ToolDraftIn
) -> ToolDraftOut:
    model_name = await load_default_llm_model_name(db, tenant_id=tenant_id)
    prompt = build_tool_draft_prompt(payload)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{settings.maas_base_url.rstrip('/')}/v1/chat/completions",
                json={
                    "model": model_name,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "你是企业 AI 平台的工具配置助手。只输出一个 JSON 对象，不要输出 Markdown。"
                                "JSON 字段必须为 name,type,summary,tool_schema,config。"
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "temperature": 0.2,
                    "max_tokens": 1200,
                },
                headers=maas_service_headers(),
            )
        response.raise_for_status()
        content = (
            ((response.json().get("choices") or [{}])[0]).get("message") or {}
        ).get("content") or ""
        data = extract_json_object(str(content))
        return normalize_tool_draft(
            data, fallback_description=payload.description, hint=payload.hint
        )
    except (httpx.HTTPError, ValueError, json.JSONDecodeError):
        return fallback_tool_draft(payload)


async def load_default_llm_model_name(db: AsyncSession, *, tenant_id: UUID) -> str:
    result = await db.execute(
        select(Model.name)
        .join(ModelChannel, ModelChannel.model_id == Model.id)
        .where(
            Model.type == "llm",
            Model.is_active.is_(True),
            ModelChannel.status == "active",
            ModelChannel.health != "failed",
            (ModelChannel.tenant_id == tenant_id) | (ModelChannel.tenant_id.is_(None)),
        )
        .order_by(ModelChannel.weight.desc(), ModelChannel.created_at.asc())
        .limit(1)
    )
    model_name = result.scalar_one_or_none()
    if not model_name:
        raise ValueError("no_active_model_channel")
    return model_name


def build_tool_draft_prompt(payload: ToolDraftIn) -> str:
    hint = payload.hint.model_dump(exclude_none=True) if payload.hint else {}
    return (
        "请根据以下需求生成一个可编辑的工具草稿。\n"
        f"需求描述：{payload.description}\n"
        f"线索：{json.dumps(hint, ensure_ascii=False)}\n"
        "要求：\n"
        "1. type 只能是 http、mcp、code、builtin；优先根据 endpoint/server_url 判断 http 或 mcp。\n"
        "2. tool_schema 必须是 JSON Schema object，properties 里写清字段 description。\n"
        "3. config 必须包含 category、group、audience、availability。"
        "category 可选 capability 或 ops；audience 可选 agent 或 admin；availability 可选 available 或 coming_soon。\n"
        "4. http config 放 url、method、headers；mcp config 按 mcp:{name,transport,server_url,auth} 结构。\n"
    )


def extract_json_object(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    if cleaned.startswith("{"):
        return json.loads(cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        return json.loads(cleaned[start : end + 1])
    raise ValueError("tool_draft_json_not_found")


def normalize_tool_draft(
    data: dict[str, Any], *, fallback_description: str, hint: Any | None
) -> ToolDraftOut:
    tool_type = str(data.get("type") or "").strip().lower()
    if tool_type not in {"http", "code", "builtin", "mcp"}:
        tool_type = (
            "mcp"
            if (
                hint
                and getattr(hint, "endpoint", None)
                and "mcp" in str(hint.endpoint).lower()
            )
            else "http"
        )
    config = data.get("config") if isinstance(data.get("config"), dict) else {}
    config = normalize_tool_config(config, tool_type=tool_type, hint=hint)
    schema = data.get("tool_schema") or data.get("schema")
    if not isinstance(schema, dict):
        schema = default_tool_schema()
    return ToolDraftOut(
        name=str(data.get("name") or fallback_description[:24] or "新建工具"),
        type=tool_type,
        summary=str(data.get("summary") or fallback_description[:80]),
        tool_schema=schema,
        config=config,
    )


def fallback_tool_draft(payload: ToolDraftIn) -> ToolDraftOut:
    tool_type = "http"
    endpoint = payload.hint.endpoint if payload.hint else None
    if endpoint and "mcp" in endpoint.lower():
        tool_type = "mcp"
    return ToolDraftOut(
        name="新建工具草稿",
        type=tool_type,
        summary=payload.description[:80],
        tool_schema=default_tool_schema(),
        config=normalize_tool_config({}, tool_type=tool_type, hint=payload.hint),
    )


def default_tool_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "需要工具处理的问题或参数。"},
        },
        "required": ["query"],
    }


def normalize_tool_config(
    config: dict[str, Any], *, tool_type: str, hint: Any | None
) -> dict[str, Any]:
    normalized = dict(config)
    normalized.setdefault("category", "capability")
    normalized.setdefault("group", "mcp" if tool_type == "mcp" else tool_type)
    normalized.setdefault("audience", "agent")
    normalized.setdefault(
        "availability", "coming_soon" if tool_type == "mcp" else "available"
    )
    if tool_type == "http":
        normalized.setdefault("url", getattr(hint, "endpoint", None) if hint else "")
        normalized.setdefault(
            "method", (getattr(hint, "method", None) if hint else None) or "GET"
        )
        normalized.setdefault("headers", {})
    if tool_type == "mcp":
        mcp = normalized.get("mcp") if isinstance(normalized.get("mcp"), dict) else {}
        mcp.setdefault("name", normalized.get("name") or "外部 MCP 服务")
        mcp.setdefault("transport", "sse")
        mcp.setdefault("server_url", getattr(hint, "endpoint", None) if hint else "")
        mcp.setdefault("auth", {"type": "none"})
        normalized["mcp"] = mcp
        normalized["availability"] = "coming_soon"
    return normalized


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
    ssrf_error = validate_http_tool_url(str(url))
    if ssrf_error is not None:
        return ssrf_error

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                follow_redirects=False,
            )
        text = response.text
        return {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": text[:12000],
        }
    except httpx.HTTPError as exc:
        return {"error": "http_tool_failed", "detail": str(exc)}


INTERNAL_HOSTNAMES = {
    "backend",
    "frontend",
    "localhost",
    "maas",
    "minio",
    "postgres",
    "redis",
    "sandbox",
}


def validate_http_tool_url(url: str) -> dict[str, str] | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return {
            "error": "ssrf_blocked",
            "detail": "Only absolute http(s) URLs are allowed.",
        }
    try:
        port = parsed.port
    except ValueError:
        return {"error": "ssrf_blocked", "detail": "Invalid URL port."}

    hostname = parsed.hostname.lower().rstrip(".")
    if hostname in allowed_http_tool_hosts():
        return None
    if hostname in INTERNAL_HOSTNAMES or hostname.endswith(".local"):
        return {
            "error": "ssrf_blocked",
            "detail": "Internal service hostnames are not allowed.",
        }

    blocked_literal = blocked_ip_literal(hostname)
    if blocked_literal is not None:
        return {
            "error": "ssrf_blocked",
            "detail": f"Blocked private or local address: {blocked_literal}.",
        }

    try:
        addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return {
            "error": "ssrf_blocked",
            "detail": "Hostname could not be resolved safely.",
        }

    for address in {item[4][0] for item in addresses}:
        if is_blocked_ip(address):
            return {
                "error": "ssrf_blocked",
                "detail": f"Blocked private or local address: {address}.",
            }
    return None


def allowed_http_tool_hosts() -> set[str]:
    return {
        host.strip().lower().rstrip(".")
        for host in settings.http_tool_allowed_hosts.split(",")
        if host.strip()
    }


def blocked_ip_literal(hostname: str) -> str | None:
    try:
        return hostname if is_blocked_ip(hostname) else None
    except ValueError:
        return None


def is_blocked_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_unspecified
        or ip.is_multicast
        or ip.is_reserved
    )


async def run_code_tool(tool: Tool, input: dict[str, Any]) -> dict[str, Any]:
    config = tool.config or {}
    code = input.get("code") or config.get("code")
    if not code:
        return {"error": "code_required"}

    payload = {
        "type": "python",
        "code": code,
        "timeout_seconds": input.get("timeout_seconds")
        or config.get("timeout_seconds")
        or 10,
    }
    try:
        async with httpx.AsyncClient(timeout=payload["timeout_seconds"] + 5) as client:
            response = await client.post(
                f"{settings.sandbox_base_url.rstrip('/')}/exec", json=payload
            )
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
    db_path = resolve_demo_data_path(
        str(input.get("db_path") or config.get("db_path") or "")
    )
    if not db_path:
        return {"error": "db_path_required"}

    sql = str(input.get("sql") or "").strip()
    if not sql:
        sql = generate_demo_sql(question)

    try:
        sql = validate_select_sql(
            sql, allowed_tables=set(config.get("allowed_tables") or ["work_orders"])
        )
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
    if (
        any(term in question for term in ("小类", "子类", "类型", "分类", "案件"))
        and "总" not in question
    ):
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
    if any(term in normalized for term in ("count", "total")) or any(
        term in question for term in ("多少", "总量", "总数", "工单量")
    ):
        return "SELECT COUNT(*) AS work_order_count FROM work_orders"
    return "SELECT task_id, accept_time, street_town, responsible_department_l3, problem_description FROM work_orders LIMIT 20"


def top_n_from_question(question: str, *, default: int) -> int:
    match = re.search(r"(?:前|top\s*)(\d{1,2})", question, flags=re.IGNORECASE)
    if not match:
        return default
    return max(1, min(int(match.group(1)), 50))


def validate_select_sql(sql: str, *, allowed_tables: set[str]) -> str:
    cleaned = sql.strip().rstrip(";")
    allowed = {table.lower() for table in allowed_tables}
    try:
        statements = sqlglot.parse(cleaned, read="sqlite")
    except sqlglot.errors.ParseError as exc:
        if contains_forbidden_metadata_token(cleaned):
            raise ValueError("forbidden_construct") from exc
        if contains_write_or_admin_token(cleaned):
            raise ValueError("write_or_admin_statement_not_allowed") from exc
        raise ValueError("sql_parse_failed") from exc

    if not statements:
        raise ValueError("only_select_allowed")
    if len(statements) > 1:
        raise ValueError("multiple_statements_not_allowed")

    statement = statements[0]
    if contains_forbidden_metadata(statement):
        raise ValueError("forbidden_construct")
    if not is_select_statement(statement):
        raise ValueError("write_or_admin_statement_not_allowed")
    if contains_write_or_admin_statement(statement):
        raise ValueError("write_or_admin_statement_not_allowed")

    physical_tables = referenced_physical_tables(statement)
    if physical_tables & SQLITE_METADATA_TABLES:
        raise ValueError("forbidden_construct")
    if not physical_tables.issubset(allowed):
        raise ValueError("table_not_allowed")

    normalized_sql = statement.sql(dialect="sqlite")
    select_expression = top_level_select(statement)
    if (
        select_expression is not None
        and not select_expression.args.get("limit")
        and not is_pure_count_query(select_expression)
    ):
        normalized_sql = f"{normalized_sql} LIMIT 50"
    return normalized_sql


SQLITE_METADATA_TABLES = {
    "sqlite_master",
    "sqlite_schema",
    "sqlite_temp_master",
    "sqlite_temp_schema",
}
SQLITE_ADMIN_KEYWORDS = {"attach", "detach", "pragma"}
WRITE_OR_ADMIN_KEYWORDS = {
    "alter",
    "create",
    "delete",
    "drop",
    "insert",
    "merge",
    "replace",
    "truncate",
    "update",
}

WRITE_OR_ADMIN_EXPRESSIONS = tuple(
    expression_type
    for expression_type in (
        getattr(exp, "Alter", None),
        getattr(exp, "Command", None),
        getattr(exp, "Create", None),
        getattr(exp, "Delete", None),
        getattr(exp, "Drop", None),
        getattr(exp, "Insert", None),
        getattr(exp, "Merge", None),
        getattr(exp, "TruncateTable", None),
        getattr(exp, "Update", None),
    )
    if expression_type is not None
)


def is_select_statement(statement: exp.Expression) -> bool:
    return top_level_select(statement) is not None


def top_level_select(statement: exp.Expression) -> exp.Select | None:
    if isinstance(statement, exp.Select):
        return statement
    if isinstance(statement, exp.With) and isinstance(statement.this, exp.Select):
        return statement.this
    return None


def contains_write_or_admin_statement(statement: exp.Expression) -> bool:
    return any(
        isinstance(node, WRITE_OR_ADMIN_EXPRESSIONS) for node in statement.walk()
    )


def contains_forbidden_metadata(statement: exp.Expression) -> bool:
    for node in statement.walk():
        class_name = node.__class__.__name__.lower()
        if class_name in {"pragma", "attach", "detach"}:
            return True
        if isinstance(node, exp.Command):
            command_sql = node.sql(dialect="sqlite").strip().lower()
            if command_sql.startswith(("pragma", "attach", "detach")):
                return True
    return False


def contains_forbidden_metadata_token(sql: str) -> bool:
    return any(token in SQLITE_ADMIN_KEYWORDS for token in sql_keyword_tokens(sql))


def contains_write_or_admin_token(sql: str) -> bool:
    return any(token in WRITE_OR_ADMIN_KEYWORDS for token in sql_keyword_tokens(sql))


def sql_keyword_tokens(sql: str) -> set[str]:
    return {
        token.text.lower()
        for token in Tokenizer(dialect="sqlite").tokenize(sql)
        if token.token_type
        not in {TokenType.STRING, TokenType.BIT_STRING, TokenType.HEX_STRING}
    }


def referenced_physical_tables(statement: exp.Expression) -> set[str]:
    cte_names = {
        normalize_sql_identifier(cte.alias_or_name)
        for cte in statement.find_all(exp.CTE)
    }
    tables: set[str] = set()
    for table in statement.find_all(exp.Table):
        table_name = normalize_sql_identifier(table.name)
        # CTE names appear as Table nodes in outer SELECTs, but they are not physical tables.
        if table_name and table_name not in cte_names:
            tables.add(table_name)
    return tables


def normalize_sql_identifier(identifier: str) -> str:
    return identifier.strip('"`[]').lower()


def is_pure_count_query(statement: exp.Select) -> bool:
    if statement.args.get("group") or statement.args.get("having"):
        return False
    expressions = statement.expressions or []
    if not expressions:
        return False
    for expression in expressions:
        projected = expression.this if isinstance(expression, exp.Alias) else expression
        if not isinstance(projected, exp.Count):
            return False
    return True


def rows_to_csv(columns: list[str], rows: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue().strip()


def summarize_query_result(
    question: str, rows: list[dict[str, Any]], columns: list[str]
) -> str:
    if not rows:
        return "未查询到符合条件的数据。"
    if len(rows) == 1 and len(columns) == 1:
        return f"{question}：{rows[0][columns[0]]}。"
    top = rows[0]
    pairs = "，".join(f"{key}={value}" for key, value in top.items())
    return f"返回 {len(rows)} 行结果，排名第一/首行是：{pairs}。"
