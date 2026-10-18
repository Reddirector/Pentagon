"""Management API for external MCP (Model Context Protocol) servers.

Provides endpoints to list configured servers, add/edit/delete custom servers,
toggle server activation, test server handshakes, and inspect remote tools
contributed to the agent registry.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import McpServer, utc_now
from app.db.session import get_db
from app.routes.agent import reset_registry
from app.security.input_validation import reject_control_characters
from app.services import mcp_bridge
from app.services.mcp_bridge import ServerConfig, parse_servers, test_server_config

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

_SLUG = re.compile(r"[^a-z0-9_]+")
_VALID_TIERS = {"read", "write", "destructive", "external_send"}

PRESET_SERVERS = [
    {
        "id": "sqlite",
        "name": "sqlite_db",
        "title": "SQLite Database",
        "description": "Inspect schemas, query tables, and execute SQL statements against local SQLite databases.",
        "command": ["uvx", "mcp-server-sqlite", "--db-path", "./pentagon.db"],
        "tier": "write",
        "category": "database",
        "env": {},
        "required_env": [],
    },
    {
        "id": "time",
        "name": "time_tools",
        "title": "Time & Timezones",
        "description": "Query current wall-clock time across any global timezone and perform timezone conversions.",
        "command": ["uvx", "mcp-server-time"],
        "tier": "read",
        "category": "utility",
        "env": {},
        "required_env": [],
    },
    {
        "id": "filesystem",
        "name": "filesystem",
        "title": "Local Filesystem",
        "description": "Securely read, list, and write files in a designated local directory path.",
        "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "./generated_files"],
        "tier": "write",
        "category": "storage",
        "env": {},
        "required_env": [],
    },
    {
        "id": "fetch",
        "name": "web_fetch",
        "title": "Web Fetch & Markdown",
        "description": "High-efficiency HTTP fetch and HTML-to-markdown conversion for external documentation.",
        "command": ["uvx", "mcp-server-fetch"],
        "tier": "read",
        "category": "web",
        "env": {},
        "required_env": [],
    },
    {
        "id": "memory",
        "name": "memory_graph",
        "title": "Knowledge Graph Memory",
        "description": "Persistent graph-based memory store for remembering entities and relations.",
        "command": ["npx", "-y", "@modelcontextprotocol/server-memory"],
        "tier": "write",
        "category": "memory",
        "env": {},
        "required_env": [],
    },
    {
        "id": "github",
        "name": "github",
        "title": "GitHub Integration",
        "description": "Search code, browse repositories, inspect commits, and manage issues and pull requests.",
        "command": ["npx", "-y", "@modelcontextprotocol/server-github"],
        "tier": "write",
        "category": "developer",
        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": ""},
        "required_env": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
    },
]


def mask_sensitive_value(key: str, value: str) -> str:
    key_upper = key.upper()
    if any(secret in key_upper for secret in ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH")):
        if len(value) <= 6:
            return "••••••"
        return f"{value[:3]}••••••{value[-3:]}"
    return value


def sanitize_env_for_display(env: dict[str, str]) -> dict[str, str]:
    return {k: mask_sensitive_value(k, str(v)) for k, v in env.items()}


class McpServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    command: list[str] = Field(min_length=1, max_length=64)
    tier: str = "write"
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        clean = reject_control_characters(value.strip().lower())
        slug = _SLUG.sub("_", clean).strip("_")
        if not slug:
            raise ValueError("Server name must contain alphanumeric characters.")
        return slug

    @field_validator("command")
    @classmethod
    def validate_command(cls, values: list[str]) -> list[str]:
        parts = [reject_control_characters(v.strip()) for v in values if v.strip()]
        if not parts:
            raise ValueError("Command cannot be empty.")
        return parts

    @field_validator("tier")
    @classmethod
    def validate_tier(cls, value: str) -> str:
        val = value.strip().lower()
        if val not in _VALID_TIERS:
            raise ValueError(f"Tier must be one of: {', '.join(sorted(_VALID_TIERS))}")
        return val


class McpServerToggle(BaseModel):
    enabled: bool


class McpTestRequest(BaseModel):
    command: list[str] = Field(min_length=1, max_length=64)
    tier: str = "write"
    env: dict[str, str] = Field(default_factory=dict)

    @field_validator("command")
    @classmethod
    def validate_command(cls, values: list[str]) -> list[str]:
        parts = [reject_control_characters(v.strip()) for v in values if v.strip()]
        if not parts:
            raise ValueError("Command cannot be empty.")
        return parts


@router.get("")
def list_mcp_servers(
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List all configured MCP servers with live session status, tool schemas, and presets."""
    active_sessions = mcp_bridge.all_sessions()
    
    # 1. Fetch DB configured servers
    db_rows = db.query(McpServer).order_by(McpServer.created_at.desc()).all()
    db_names = {row.name for row in db_rows}
    
    # 2. Fetch settings servers
    env_configs, env_problems = parse_servers(settings.mcp_servers)

    servers_out: list[dict[str, Any]] = []

    for row in db_rows:
        session = active_sessions.get(row.name)
        status = "disabled" if not row.enabled else (
            "connected" if session and session.alive else (
                "error" if session and session.last_error else "disconnected"
            )
        )
        tools = [
            {
                "name": spec.name,
                "remote_name": session.remote_names.get(spec.name, spec.name) if session else spec.name,
                "description": spec.description,
                "tier": spec.tier,
                "risk_category": spec.risk_category,
                "parameters": spec.parameters,
            }
            for spec in (session.tools if session else [])
        ]
        servers_out.append({
            "name": row.name,
            "command": list(row.command),
            "tier": row.tier,
            "env": sanitize_env_for_display(row.env or {}),
            "has_secrets": any(bool(v) for v in (row.env or {}).values()),
            "enabled": row.enabled,
            "status": status,
            "last_error": session.last_error if session else None,
            "tools": tools,
            "tools_count": len(tools),
            "source": "database",
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        })

    # Add environment servers not overridden in DB
    for cfg in env_configs:
        if cfg.name in db_names:
            continue
        session = active_sessions.get(cfg.name)
        status = "connected" if session and session.alive else (
            "error" if session and session.last_error else "disconnected"
        )
        tools = [
            {
                "name": spec.name,
                "remote_name": session.remote_names.get(spec.name, spec.name) if session else spec.name,
                "description": spec.description,
                "tier": spec.tier,
                "risk_category": spec.risk_category,
                "parameters": spec.parameters,
            }
            for spec in (session.tools if session else [])
        ]
        servers_out.append({
            "name": cfg.name,
            "command": list(cfg.command),
            "tier": cfg.tier,
            "env": sanitize_env_for_display(cfg.env),
            "has_secrets": any(bool(v) for v in cfg.env.values()),
            "enabled": True,
            "status": status,
            "last_error": session.last_error if session else None,
            "tools": tools,
            "tools_count": len(tools),
            "source": "environment",
            "created_at": None,
            "updated_at": None,
        })

    all_problems = list(mcp_bridge.problems()) + env_problems

    return {
        "servers": servers_out,
        "problems": all_problems,
        "presets": PRESET_SERVERS,
    }


@router.post("")
async def create_or_update_mcp_server(
    payload: McpServerCreate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Add or update an MCP server configuration, persisting it and starting the session."""
    existing = db.query(McpServer).filter(McpServer.name == payload.name).first()

    clean_env = {str(k).strip(): str(v).strip() for k, v in payload.env.items() if str(k).strip()}

    if existing:
        existing.command = payload.command
        existing.tier = payload.tier
        # Only overwrite non-masked env vars if values provided
        merged_env = dict(existing.env or {})
        for k, v in clean_env.items():
            if "••••••" not in v:
                merged_env[k] = v
        existing.env = merged_env
        existing.enabled = payload.enabled
        existing.updated_at = utc_now()
        server_row = existing
    else:
        server_row = McpServer(
            name=payload.name,
            command=payload.command,
            tier=payload.tier,
            env=clean_env,
            enabled=payload.enabled,
        )
        db.add(server_row)

    db.commit()
    db.refresh(server_row)

    # If enabled, start or update session in the live bridge
    config = ServerConfig(
        name=server_row.name,
        command=tuple(server_row.command),
        tier=server_row.tier,
        env=server_row.env or {},
    )

    if server_row.enabled:
        success, err = await mcp_bridge.add_or_update(config)
        reset_registry()
    else:
        await mcp_bridge.remove(server_row.name)
        reset_registry()

    session = mcp_bridge.session(server_row.name)
    tools = [
        {
            "name": spec.name,
            "remote_name": session.remote_names.get(spec.name, spec.name) if session else spec.name,
            "description": spec.description,
            "tier": spec.tier,
            "risk_category": spec.risk_category,
        }
        for spec in (session.tools if session else [])
    ]

    return {
        "ok": True,
        "server": {
            "name": server_row.name,
            "command": list(server_row.command),
            "tier": server_row.tier,
            "env": sanitize_env_for_display(server_row.env or {}),
            "enabled": server_row.enabled,
            "status": "connected" if session and session.alive else ("disabled" if not server_row.enabled else "error"),
            "last_error": session.last_error if session else None,
            "tools": tools,
            "tools_count": len(tools),
            "source": "database",
        },
    }


@router.patch("/{name}/toggle")
async def toggle_mcp_server(
    name: str,
    payload: McpServerToggle,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Toggle an MCP server on or off."""
    row = db.query(McpServer).filter(McpServer.name == name).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found.")

    row.enabled = payload.enabled
    row.updated_at = utc_now()
    db.commit()
    db.refresh(row)

    config = ServerConfig(
        name=row.name,
        command=tuple(row.command),
        tier=row.tier,
        env=row.env or {},
    )

    if row.enabled:
        await mcp_bridge.add_or_update(config)
    else:
        await mcp_bridge.remove(row.name)

    reset_registry()

    session = mcp_bridge.session(row.name)
    return {
        "ok": True,
        "name": row.name,
        "enabled": row.enabled,
        "status": "connected" if session and session.alive else ("disabled" if not row.enabled else "error"),
    }


@router.delete("/{name}")
async def delete_mcp_server(
    name: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Delete an MCP server configuration from the database and close its session."""
    row = db.query(McpServer).filter(McpServer.name == name).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found.")

    db.delete(row)
    db.commit()

    await mcp_bridge.remove(name)
    reset_registry()

    return {"ok": True, "message": f"MCP server '{name}' deleted."}


@router.post("/test")
async def test_adhoc_mcp_server(
    payload: McpTestRequest,
) -> dict[str, Any]:
    """Test an arbitrary MCP server command in an isolated session before saving it."""
    config = ServerConfig(
        name="test_adhoc",
        command=tuple(payload.command),
        tier=payload.tier,
        env=payload.env,
    )
    result = await test_server_config(config, timeout=12.0)
    return result


@router.post("/{name}/test")
async def test_existing_mcp_server(
    name: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Test an existing configured MCP server's handshake and tool response."""
    row = db.query(McpServer).filter(McpServer.name == name).first()
    if row:
        config = ServerConfig(
            name=row.name,
            command=tuple(row.command),
            tier=row.tier,
            env=row.env or {},
        )
    else:
        env_configs, _ = parse_servers(settings.mcp_servers)
        matching = next((c for c in env_configs if c.name == name), None)
        if not matching:
            raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found.")
        config = matching

    result = await test_server_config(config, timeout=12.0)
    return result


@router.post("/reload")
async def reload_all_mcp_servers() -> dict[str, Any]:
    """Reconnect all configured MCP servers and refresh the agent registry."""
    await mcp_bridge.connect_all()
    reset_registry()
    sessions = mcp_bridge.all_sessions()
    active_count = sum(1 for s in sessions.values() if s.alive)
    return {
        "ok": True,
        "total_configured": len(sessions),
        "active_connected": active_count,
        "problems": list(mcp_bridge.problems()),
    }
