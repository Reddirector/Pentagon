"""Bridge to MCP servers the user configured: their tools, our envelope.

An MCP (Model Context Protocol) server is a separate process the user lists
in ``Settings.mcp_servers``; over a stdio JSON-RPC session it can offer tools
this agent does not have. This module owns three things:

- **Config is the only source.** Only servers named in the settings JSON are
  ever spawned -- never a command a model, a prompt or a web page asks for.
  Commands run as argv lists (no shell) with an inherited environment plus
  per-server overrides.
- **Lifecycle.** ``connect_all`` (app lifespan) spawns each server, performs
  the ``initialize`` handshake and caches ``tools/list`` (paginated). A
  server that fails is recorded in ``problems`` and never breaks startup.
  A server that dies later is restarted by its next call -- one fresh start
  per call, never a crash loop.
- **Translation.** Remote tools become prefixed ``mcp_<server>_<tool>``
  ToolSpecs: MCP ``readOnlyHint``/``destructiveHint`` annotations map onto
  our permission tiers (read-only runs, destructive always asks), and tools
  without annotations take the server's configured tier, defaulting to
  ``write`` so an unknown capability is approval-gated instead of auto-run.
  Results are flattened to text inside the usual ToolResult envelope and
  marked ``untrusted`` like any other third-party text.

Concurrency: one process per server and one in-flight call at a time behind
a per-server lock -- MCP stdio servers are generally not written for
interleaved requests, and serialising is the difference between a queue and
corrupted frames. Sessions are bound to the event loop that connected them
(the app lifespan's loop); tests must connect and call inside one
``asyncio.run``.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Any

from app.agent.schemas import ToolResult, ToolSpec
from app.config import settings

_INIT_TIMEOUT_SECONDS = 10.0
_CALL_TIMEOUT_SECONDS = 30.0
_SHUTDOWN_TIMEOUT_SECONDS = 3.0
# Sent in the handshake; we accept whatever version the server answers with.
# Anything both sides speak is the tools/* surface used here.
_PROTOCOL_VERSION = "2024-11-05"
_CLIENT_INFO = {"name": "pentagon", "version": "0.1.0"}
_TIERS = {"read", "write", "destructive", "external_send"}


class BridgeError(RuntimeError):
    """The bridge could not get an answer out of the server."""


class ConnectionLost(BridgeError):
    """The process is gone or the pipe broke -- restarting is legitimate."""


class CallTimeout(BridgeError):
    """The server stopped answering; the session is dropped after this."""


class RemoteError(BridgeError):
    """The server answered with a JSON-RPC error -- a normal refusal."""


@dataclass(frozen=True)
class ServerConfig:
    name: str
    command: tuple[str, ...]
    tier: str = "write"
    env: dict[str, str] = field(default_factory=dict)


def parse_servers(raw: str) -> tuple[list[ServerConfig], list[str]]:
    """Settings JSON -> (configs, problems). Never raises on bad input."""
    configs: list[ServerConfig] = []
    problems: list[str] = []
    try:
        data = json.loads(raw or "[]")
    except ValueError as exc:
        return [], [f"mcp_servers is not valid JSON: {exc}"]
    if not isinstance(data, list):
        return [], ["mcp_servers must be a JSON array of server objects"]
    seen: set[str] = set()
    for index, entry in enumerate(data):
        if not isinstance(entry, dict):
            problems.append(f"mcp_servers[{index}] is not an object")
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            problems.append(f"mcp_servers[{index}] needs a non-empty name")
            continue
        name = re.sub(r"[^a-z0-9_]+", "_", name.strip().lower()).strip("_")
        if not name:
            problems.append(f"mcp_servers[{index}] name has no usable characters")
            continue
        if name in seen:
            problems.append(f"mcp server '{name}' is listed twice; the second is ignored")
            continue
        command = entry.get("command")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) and part for part in command)
        ):
            problems.append(
                f"mcp server '{name}' needs a command array of non-empty strings"
            )
            continue
        tier = entry.get("tier", "write")
        if tier not in _TIERS:
            problems.append(
                f"mcp server '{name}' has unknown tier {tier!r}; using 'write'"
            )
            tier = "write"
        env = entry.get("env", {})
        if not isinstance(env, dict):
            problems.append(f"mcp server '{name}' env must be an object; ignoring it")
            env = {}
        seen.add(name)
        configs.append(
            ServerConfig(
                name=name,
                command=tuple(command),
                tier=tier,
                env={str(k): str(v) for k, v in env.items()},
            )
        )
    return configs, problems


def safe_tool_name(server: str, tool: str) -> str:
    """mcp_<server>_<tool>, lower snake -- the registry's hard requirement."""
    name = re.sub(r"[^a-z0-9]+", "_", f"mcp_{server}_{tool}".lower()).strip("_")
    return name or "mcp_tool"


def derive_tier(annotations: dict[str, Any], configured: str) -> str:
    """MCP annotations, when present, are the server's own declaration.

    readOnlyHint=True is the only path down to read (auto-run); a declared
    destructiveHint=True escalates to always-ask. Everything else falls back
    to the server's configured tier -- unknown capabilities stay gated.
    """
    if annotations.get("readOnlyHint") is True:
        return "read"
    if annotations.get("destructiveHint") is True:
        return "destructive"
    return configured if configured in _TIERS else "write"


def build_spec(config: ServerConfig, entry: dict[str, Any]) -> ToolSpec:
    """One remote tool description -> our ToolSpec (validated on register)."""
    remote_name = str(entry.get("name") or "").strip()
    annotations = entry.get("annotations")
    if not isinstance(annotations, dict):
        annotations = {}
    schema = entry.get("inputSchema")
    if not isinstance(schema, dict) or schema.get("type") != "object":
        schema = {"type": "object", "properties": {}}
    description = str(entry.get("description") or "").strip() or "No description."
    return ToolSpec(
        name=safe_tool_name(config.name, remote_name or "tool"),
        description=(
            f"MCP tool '{remote_name or 'tool'}' provided by the external"
            f" server '{config.name}'. {description}"
        ),
        parameters=schema,
        tier=derive_tier(annotations, config.tier),
        timeout_s=int(_CALL_TIMEOUT_SECONDS) + 15,
        cacheable=False,
        # Unknown servers get unknown semantics: never replay, never run two
        # calls into one process at once.
        idempotent=False,
        parallel_safe=False,
        untrusted=True,
        tags=("mcp", config.name),
    )


def flatten_content(content: Any) -> str:
    """MCP content blocks -> the single text body the model reads."""
    parts: list[str] = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            parts.append(str(block.get("text") or ""))
        elif kind == "image":
            parts.append(f"[image omitted: {block.get('mimeType') or 'image'}]")
        elif kind == "resource":
            resource = block.get("resource")
            if isinstance(resource, dict) and isinstance(resource.get("text"), str):
                parts.append(resource["text"])
            else:
                uri = resource.get("uri", "resource") if isinstance(resource, dict) else "resource"
                parts.append(f"[resource: {uri}]")
        else:
            parts.append(f"[{kind or 'unknown'} content omitted]")
    text = "\n".join(part for part in parts if part).strip()
    return text or "(the server returned no content)"


class McpSession:
    """One spawned server: handshake, cached tools, serialized calls."""

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.tools: list[ToolSpec] = []
        self.remote_names: dict[str, str] = {}  # our name -> their name
        self.last_error: str | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._drain_task: asyncio.Task[None] | None = None
        self._stderr_tail: deque[str] = deque(maxlen=40)
        self._lock = asyncio.Lock()
        self._next_id = 0

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self) -> None:
        """Spawn, handshake, cache tools/list. Raises BridgeError on failure."""
        await self.close()
        env = {**os.environ, **self.config.env} if self.config.env else None
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *self.config.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except OSError as exc:
            self.last_error = f"could not spawn: {exc}"
            raise ConnectionLost(f"mcp server '{self.config.name}' {self.last_error}") from exc
        self._drain_task = asyncio.create_task(self._drain_stderr())
        try:
            await self._request(
                "initialize",
                {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": _CLIENT_INFO,
                },
                timeout=_INIT_TIMEOUT_SECONDS,
            )
            await self._notify("notifications/initialized")
            await self._refresh_tools()
        except BridgeError as exc:
            self.last_error = str(exc)
            await self.close()
            raise
        self.last_error = None

    async def _drain_stderr(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            while True:
                line = await proc.stderr.readline()
                if not line:
                    return
                self._stderr_tail.append(
                    line.decode(errors="replace").rstrip()[:300]
                )
        except asyncio.CancelledError:
            raise
        except (ValueError, OSError):
            return

    async def _refresh_tools(self) -> None:
        cursor: str | None = None
        entries: list[dict[str, Any]] = []
        while True:
            params = {"cursor": cursor} if cursor else {}
            payload = await self._request(
                "tools/list", params, timeout=_INIT_TIMEOUT_SECONDS
            )
            batch = payload.get("tools")
            if isinstance(batch, list):
                entries.extend(e for e in batch if isinstance(e, dict))
            cursor = payload.get("nextCursor")
            if not isinstance(cursor, str) or not cursor:
                break
        self.tools = [build_spec(self.config, entry) for entry in entries]
        self.remote_names = {
            spec.name: str(entry.get("name") or "")
            for spec, entry in zip(self.tools, entries)
        }

    async def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """tools/call with at most one fresh start after a lost connection."""
        attempts = 0
        while True:
            attempts += 1
            if not self.alive:
                await self.start()
            try:
                return await self._request(
                    "tools/call",
                    {"name": name, "arguments": args},
                    timeout=_CALL_TIMEOUT_SECONDS,
                )
            except ConnectionLost:
                # Dead mid-call: one restart, then report honestly.
                await self.close()
                if attempts >= 2:
                    raise
            except CallTimeout:
                # Wedged, not dead: drop it so the next call starts fresh.
                await self.close()
                raise

    async def _request(
        self, method: str, params: dict[str, Any], *, timeout: float
    ) -> dict[str, Any]:
        proc = self._require_proc()
        self._next_id += 1
        request_id = self._next_id
        frame = (
            json.dumps(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            )
            + "\n"
        ).encode()
        async with self._lock:
            try:
                proc.stdin.write(frame)
                await proc.stdin.drain()
                message = await asyncio.wait_for(
                    self._read_until(request_id), timeout
                )
            except asyncio.TimeoutError as exc:
                raise CallTimeout(
                    f"'{method}' timed out after {timeout:.0f}s"
                ) from exc
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise ConnectionLost(
                    f"mcp server '{self.config.name}' closed the connection"
                ) from exc
        if "error" in message:
            error = message["error"] if isinstance(message["error"], dict) else {}
            raise RemoteError(
                f"{error.get('message') or 'unknown error'}"
                f" (code {error.get('code', '?')})"
            )
        result = message.get("result")
        return result if isinstance(result, dict) else {}

    async def _read_until(self, request_id: int) -> dict[str, Any]:
        proc = self._require_proc()
        while True:
            try:
                line = await proc.stdout.readline()
            except (ValueError, OSError) as exc:
                raise ConnectionLost(
                    f"mcp server '{self.config.name}' stopped talking: {exc}"
                ) from exc
            if not line:
                tail = " | ".join(list(self._stderr_tail)[-3:])
                raise ConnectionLost(
                    f"mcp server '{self.config.name}' exited"
                    f" (rc={proc.returncode})" + (f": {tail}" if tail else "")
                )
            try:
                message = json.loads(line)
            except ValueError:
                # Not JSON on stdout: MCP mandates JSONL, but a stray log
                # line must not kill the session.
                continue
            if not isinstance(message, dict):
                continue
            if message.get("method") is not None and "id" in message:
                # The server is asking US something (ping, roots/list...).
                # Answer inside this same critical section -- the lock is
                # already held, so a direct write cannot deadlock.
                await self._answer_server_request(message)
                continue
            if message.get("id") == request_id:
                return message
            # Notifications and stale responses: requests are serialised
            # behind the lock, so nothing else can belong to this waiter.

    async def _answer_server_request(self, message: dict[str, Any]) -> None:
        proc = self._require_proc()
        method = message.get("method")
        if method == "ping":
            reply: dict[str, Any] = {"jsonrpc": "2.0", "id": message["id"], "result": {}}
        else:
            reply = {
                "jsonrpc": "2.0",
                "id": message["id"],
                "error": {"code": -32601, "message": "method not supported by the Pentagon MCP bridge"},
            }
        try:
            proc.stdin.write((json.dumps(reply) + "\n").encode())
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass  # the read loop will notice the death on the next line

    async def _notify(self, method: str) -> None:
        proc = self._require_proc()
        async with self._lock:
            try:
                proc.stdin.write(
                    (json.dumps({"jsonrpc": "2.0", "method": method}) + "\n").encode()
                )
                await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise ConnectionLost(
                    f"mcp server '{self.config.name}' closed the connection"
                ) from exc

    def _require_proc(self) -> asyncio.subprocess.Process:
        if self._proc is None or self._proc.returncode is not None:
            raise ConnectionLost(f"mcp server '{self.config.name}' is not running")
        return self._proc

    async def close(self) -> None:
        """Stop the process; never raises (used from every error path)."""
        proc, self._proc = self._proc, None
        drain, self._drain_task = self._drain_task, None
        if drain is not None:
            drain.cancel()
        if proc is None:
            return
        try:
            if proc.stdin is not None and not proc.stdin.is_closing():
                proc.stdin.close()
            await asyncio.wait_for(proc.wait(), _SHUTDOWN_TIMEOUT_SECONDS)
        except (asyncio.TimeoutError, RuntimeError, ValueError, OSError):
            try:
                proc.kill()
            except (ProcessLookupError, OSError, RuntimeError):
                return
            try:
                await asyncio.wait_for(proc.wait(), _SHUTDOWN_TIMEOUT_SECONDS)
            except (asyncio.TimeoutError, RuntimeError, ValueError, OSError):
                pass


class McpBridge:
    """All configured sessions, plus the registration and call surfaces."""

    def __init__(self) -> None:
        self._sessions: dict[str, McpSession] = {}
        self.problems: list[str] = []

    async def connect_all(self) -> None:
        """Parse settings, spawn every server. Failures are recorded, not raised."""
        await self.shutdown()
        configs, problems = parse_servers(settings.mcp_servers)
        self.problems = list(problems)
        for config in configs:
            session = McpSession(config)
            self._sessions[config.name] = session
            try:
                await session.start()
            except BridgeError as exc:
                session.last_error = str(exc)
                self.problems.append(f"server '{config.name}': {exc}")

    def session(self, name: str) -> McpSession | None:
        return self._sessions.get(name)

    def registered_tools(self) -> list[tuple[ToolSpec, Any]]:
        """(spec, handler) pairs for bootstrap. Empty until connect_all ran.

        Names are made unique here so two similarly-named servers can never
        collide into a DuplicateToolError that kills the whole registry.
        """
        pairs: list[tuple[ToolSpec, Any]] = []
        taken: set[str] = set()
        for session in self._sessions.values():
            for spec in session.tools:
                remote_name = session.remote_names.get(spec.name, spec.name)
                name = spec.name
                suffix = 2
                while name in taken:
                    name = f"{spec.name}_{suffix}"
                    suffix += 1
                taken.add(name)
                if name != spec.name:
                    spec = replace(spec, name=name)
                pairs.append((spec, self._make_handler(session, remote_name)))
        return pairs

    def _make_handler(self, session: McpSession, remote_name: str) -> Any:
        async def _run(args: dict[str, Any], ctx: Any) -> ToolResult:
            try:
                payload = await session.call_tool(remote_name, args)
            except RemoteError as exc:
                return ToolResult.failure(
                    "UPSTREAM",
                    f"MCP server '{session.config.name}' refused the call: {exc}.",
                    hint="Fix the arguments or ask the user; the server answered with an error.",
                )
            except CallTimeout as exc:
                return ToolResult.failure(
                    "TIMEOUT",
                    f"MCP server '{session.config.name}' did not answer in time ({exc}).",
                    hint="The server was dropped; the next call starts it fresh.",
                )
            except BridgeError as exc:
                return ToolResult.failure(
                    "UPSTREAM",
                    f"MCP server '{session.config.name}' is unavailable: {exc}.",
                    hint="It will be restarted on the next call; check the server's logs.",
                )
            if payload.get("isError"):
                detail = flatten_content(payload.get("content"))[:300]
                return ToolResult.failure(
                    "UPSTREAM",
                    f"MCP tool '{remote_name}' reported an error: {detail}",
                    hint=f"The server '{session.config.name}' answered the call.",
                )
            return ToolResult.success(
                {
                    "server": session.config.name,
                    "tool": remote_name,
                    "content": flatten_content(payload.get("content")),
                }
            )

        return _run

    async def shutdown(self) -> None:
        sessions = list(self._sessions.values())
        self._sessions.clear()
        for session in sessions:
            await session.close()

    def discard(self) -> None:
        """Forget sessions without awaiting (used only from tests)."""
        self._sessions.clear()


BRIDGE = McpBridge()


async def connect_all() -> None:
    await BRIDGE.connect_all()


async def shutdown() -> None:
    await BRIDGE.shutdown()


def registered_tools() -> list[tuple[ToolSpec, Any]]:
    return BRIDGE.registered_tools()


def session(name: str) -> McpSession | None:
    return BRIDGE.session(name)


def problems() -> list[str]:
    return list(BRIDGE.problems)
