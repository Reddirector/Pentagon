"""Verify the live Supabase RLS policies without leaving probe rows behind.

Run only against a disposable Supabase project. The script signs in as two
existing Auth users, seeds one owner-A fixture per table with the service role,
checks client reads and writes against those fixtures, and removes only the
fixtures it created. It never creates Auth users or prints keys/passwords.

Required environment variables are documented in
``docs/SUPABASE_RLS_VERIFICATION.md``.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from typing import Any

REQUIRED = (
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_TEST_EMAIL_A",
    "SUPABASE_TEST_PASSWORD_A",
    "SUPABASE_TEST_EMAIL_B",
    "SUPABASE_TEST_PASSWORD_B",
)

OWNED_TABLES = (
    "conversations",
    "messages",
    "files",
    "feedback",
    "action_audit",
    "collections",
    "collection_files",
    "conversation_collections",
    "chunks",
    "kg_entities",
    "kg_relations",
    "kg_provenance",
    "kg_communities",
    "index_jobs",
)
BACKEND_ONLY_TABLES = ("user_secrets", "mcp_connections", "user_settings")
ALL_TABLES = OWNED_TABLES + BACKEND_ONLY_TABLES

# RLS permits reading one's own action_audit rows, but its SQL policy is
# intentionally select-only. The owner-write assertion must reflect that.
READ_ONLY_TABLES = frozenset({"action_audit"})

# These tables have composite or user_id primary keys instead of an `id` key.
MATCH_COLUMNS = {
    "collection_files": ("collection_id", "file_id"),
    "conversation_collections": ("conversation_id", "collection_id"),
    "user_secrets": ("user_id",),
    "user_settings": ("user_id",),
}


def _uuid() -> str:
    return str(uuid.uuid4())


def _sample_rows(user_a: str) -> dict[str, dict[str, Any]]:
    """Build dependency-ordered, valid minimal rows for every public table."""
    conversation = _uuid()
    message = _uuid()
    file_id = _uuid()
    collection = _uuid()
    chunk = _uuid()
    entity = _uuid()

    return {
        "conversations": {
            "id": conversation,
            "user_id": user_a,
            "title": "rls-audit",
            "model": "rls-audit-model",
        },
        "messages": {
            "id": message,
            "conversation_id": conversation,
            "user_id": user_a,
            "role": "assistant",
            "content": "RLS verification fixture",
        },
        "files": {
            "id": file_id,
            "conversation_id": conversation,
            "user_id": user_a,
            "storage_path": "rls-audit/fixture.md",
            "filename": "fixture.md",
            "kind": "document",
            "status": "ready",
        },
        "feedback": {
            "id": _uuid(),
            "message_id": message,
            "user_id": user_a,
            "value": "up",
        },
        "action_audit": {
            "id": _uuid(),
            "user_id": user_a,
            "tool": "rls-audit",
            "args": {},
            "decision": "approved",
            "result_summary": "RLS verification fixture",
        },
        "collections": {
            "id": collection,
            "user_id": user_a,
            "name": "rls-audit",
            "embedding_model": "rls-audit/v1",
        },
        "collection_files": {
            "collection_id": collection,
            "file_id": file_id,
            "user_id": user_a,
        },
        "conversation_collections": {
            "conversation_id": conversation,
            "collection_id": collection,
            "user_id": user_a,
        },
        "chunks": {
            "id": chunk,
            "user_id": user_a,
            "collection_id": collection,
            "file_id": file_id,
            "ord": 0,
            "text": "RLS verification fixture",
        },
        "kg_entities": {
            "id": entity,
            "user_id": user_a,
            "collection_id": collection,
            "canonical_name": "RLS audit fixture",
            "names": {},
            "aliases": [],
            "type": "Test",
        },
        "kg_relations": {
            "id": _uuid(),
            "user_id": user_a,
            "collection_id": collection,
            "source_id": entity,
            "target_id": entity,
            "type": "related",
        },
        "kg_provenance": {
            "id": _uuid(),
            "user_id": user_a,
            "collection_id": collection,
            "entity_id": entity,
            "relation_id": None,
            "chunk_id": chunk,
        },
        "kg_communities": {
            "id": _uuid(),
            "user_id": user_a,
            "collection_id": collection,
            "level": 0,
            "entity_ids": [entity],
            "stale": True,
        },
        "index_jobs": {
            "id": _uuid(),
            "user_id": user_a,
            "collection_id": collection,
            "kind": "rls-audit",
        },
        # A user may already have these rows. main() reuses an existing row
        # without reading or changing its secret/configuration fields.
        "user_secrets": {"user_id": user_a, "nvidia_key_enc": "rls-audit-placeholder", "nvidia_key_last4": "0000"},
        "mcp_connections": {
            "id": _uuid(),
            "user_id": user_a,
            "server": "rls-audit-" + _uuid(),
            "credentials_enc": None,
            "config": {},
            "enabled": False,
        },
        "user_settings": {"user_id": user_a, "shell_enabled": False, "always_allow": []},
    }


def _anonymous_client(url: str, key: str):
    from supabase import create_client

    return create_client(url, key)


def _as_user(url: str, anon_key: str, email: str, password: str):
    client = _anonymous_client(url, anon_key)
    response = client.auth.sign_in_with_password({"email": email, "password": password})
    return client, response.user.id


def _match(table: str, row: dict[str, Any]) -> dict[str, Any]:
    columns = MATCH_COLUMNS.get(table, ("id",))
    return {column: row[column] for column in columns}


def _error_code(exc: Exception) -> str | None:
    code = getattr(exc, "code", None)
    if code:
        return str(code)
    # supabase-py APIError versions differ in whether `code` is an attribute.
    try:
        payload = json.loads(str(exc))
    except (TypeError, ValueError):
        return None
    return str(payload.get("code")) if payload.get("code") else None


def _error_text(exc: Exception) -> str:
    message = getattr(exc, "message", None) or str(exc)
    # Never let an HTTP client exception echo the configured bearer token.
    for secret_name in ("SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_TEST_PASSWORD_A", "SUPABASE_TEST_PASSWORD_B"):
        secret = os.environ.get(secret_name)
        if secret:
            message = message.replace(secret, "[redacted]")
    return " ".join(str(message).split())[:180]


def _is_permission_denial(exc: Exception) -> bool:
    code = _error_code(exc)
    message = _error_text(exc).lower()
    return code == "42501" or "row-level security" in message or "permission denied" in message


def _table_rows(client, table: str, selector: dict[str, Any]) -> list[dict[str, Any]]:
    response = client.table(table).select("*").match(selector).execute()
    return response.data or []


def _read_result(client, table: str, row: dict[str, Any], *, should_read: bool) -> str:
    try:
        found = _table_rows(client, table, _match(table, row))
    except Exception as exc:
        if not should_read and _is_permission_denial(exc):
            return "ok"
        return f"unexpected {_error_code(exc) or type(exc).__name__}: {_error_text(exc)}"
    if should_read:
        if len(found) == 1 and found[0].get("user_id") == row["user_id"]:
            return "ok"
        return f"owner read expected one owned row, got {len(found)}"
    if found:
        return f"read exposed {len(found)} row(s) owned by user A"
    return "ok"


def _service_owner(client, table: str, row: dict[str, Any]) -> str | None:
    """Read only the owner marker after an attempted foreign write."""
    try:
        rows = (
            client.table(table)
            .select("user_id")
            .match(_match(table, row))
            .execute()
            .data
            or []
        )
    except Exception:
        return None
    return str(rows[0]["user_id"]) if len(rows) == 1 else None


def _update_result(client, service, table: str, row: dict[str, Any], *, actor: str, allowed: bool, owner_id: str) -> str:
    selector = _match(table, row)
    try:
        response = (
            client.table(table)
            .update({"user_id": owner_id if allowed else actor})
            .match(selector)
            .select(",".join(selector))
            .execute()
        )
    except Exception as exc:
        if not allowed and _is_permission_denial(exc):
            return "ok"
        if allowed:
            return f"owner update failed ({_error_code(exc) or type(exc).__name__}): {_error_text(exc)}"
        return f"unexpected {_error_code(exc) or type(exc).__name__}: {_error_text(exc)}"

    changed = response.data or []
    if allowed:
        return "ok" if len(changed) == 1 else f"owner update expected one row, got {len(changed)}"
    actual_owner = _service_owner(service, table, row)
    if changed or actual_owner != owner_id:
        # Restore a leaked owner marker before continuing, then report the
        # unauthorized write as a real policy failure.
        try:
            service.table(table).update({"user_id": owner_id}).match(selector).execute()
        except Exception:
            pass
        return "foreign update changed or returned user A's row"
    return "ok"


def _insert_result(client, table: str, row: dict[str, Any], *, denied: bool) -> str:
    try:
        response = client.table(table).insert(row).select("user_id").execute()
    except Exception as exc:
        if denied and _is_permission_denial(exc):
            return "ok"
        # A duplicate/constraint error is not proof of RLS. It means the call
        # got farther than an authorization refusal and must fail this probe.
        return f"write was not refused by RLS ({_error_code(exc) or type(exc).__name__}): {_error_text(exc)}"
    if response.data:
        return "write went through"
    return "write returned no row; outcome is ambiguous"


def _check_openapi(url: str, service_key: str) -> tuple[bool, list[str], str | None]:
    request = urllib.request.Request(
        url.rstrip("/") + "/rest/v1/",
        headers={
            "apikey": service_key,
            "Authorization": "Bearer " + service_key,
            "Accept": "application/openapi+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            spec = json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8", "replace"))
            error = f"{body.get('code', exc.code)}: {body.get('message', 'OpenAPI request failed')}"
        except Exception:
            error = f"HTTP {exc.code}"
        return False, [], error
    except Exception as exc:
        return False, [], f"{type(exc).__name__}: {str(exc)[:160]}"
    paths = spec.get("paths", {})
    missing = [table for table in ALL_TABLES if f"/{table}" not in paths]
    return not missing, missing, None


def _seed(service, rows: dict[str, dict[str, Any]], created: list[tuple[str, dict[str, Any]]]) -> None:
    for table in OWNED_TABLES:
        response = service.table(table).insert(rows[table]).select(",".join(_match(table, rows[table]))).execute()
        # Track the generated key before validating the response so cleanup
        # still attempts deletion if the insert committed but returned an
        # unexpected representation.
        created.append((table, rows[table]))
        if len(response.data or []) != 1:
            raise RuntimeError(f"service role did not return its {table} fixture")

    for table in BACKEND_ONLY_TABLES:
        row = rows[table]
        selector = _match(table, row)
        # Do not overwrite a pre-existing secret or settings row. Its user_id
        # is sufficient to probe client isolation; secret/config fields are
        # never selected or printed.
        existing = service.table(table).select("user_id").match(selector).execute().data or []
        if existing:
            row.update(existing[0])
            continue
        response = service.table(table).insert(row).select("user_id").execute()
        created.append((table, row))
        if len(response.data or []) != 1:
            raise RuntimeError(f"service role did not return its {table} fixture")


def _cleanup(service, created: list[tuple[str, dict[str, Any]]], service_probe: dict[str, Any] | None) -> list[str]:
    order = (
        "index_jobs", "kg_provenance", "kg_relations", "kg_communities", "kg_entities",
        "chunks", "conversation_collections", "collection_files", "feedback",
        "action_audit", "files", "messages", "collections", "conversations",
        "mcp_connections", "user_settings", "user_secrets",
    )
    pending = list(created)
    errors: list[str] = []
    for table in order:
        for current_table, row in reversed(pending):
            if current_table != table:
                continue
            try:
                service.table(table).delete().match(_match(table, row)).execute()
            except Exception as exc:
                errors.append(f"{table}: {_error_code(exc) or type(exc).__name__}")
            pending.remove((current_table, row))
    if service_probe is not None:
        try:
            service.table("conversations").delete().match(_match("conversations", service_probe)).execute()
        except Exception as exc:
            errors.append(f"service-role probe: {_error_code(exc) or type(exc).__name__}")
    return errors


def main() -> int:
    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing:
        print("missing env (set and re-run):", ", ".join(missing))
        return 2

    url = os.environ["SUPABASE_URL"]
    anon_key = os.environ["SUPABASE_ANON_KEY"]
    service_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

    available, missing_tables, error = _check_openapi(url, service_key)
    if error:
        print(f"BLOCKED  PostgREST schema preflight failed: {error}")
        return 2
    if not available:
        print("BLOCKED  PostgREST cannot resolve these public tables; no RLS probes were run:")
        print("  " + ", ".join(missing_tables))
        print("This is a schema/visibility/cache failure, not an RLS pass or failure.")
        print("Confirm the tables in information_schema, ensure public is exposed, then notify pgrst to reload schema.")
        return 2

    try:
        user_a, uid_a = _as_user(url, anon_key, os.environ["SUPABASE_TEST_EMAIL_A"], os.environ["SUPABASE_TEST_PASSWORD_A"])
        user_b, uid_b = _as_user(url, anon_key, os.environ["SUPABASE_TEST_EMAIL_B"], os.environ["SUPABASE_TEST_PASSWORD_B"])
    except Exception as exc:
        print(f"BLOCKED  Auth sign-in failed ({type(exc).__name__}); no credentials were printed.")
        return 2

    rows = _sample_rows(uid_a)
    service = _anonymous_client(url, service_key)
    created: list[tuple[str, dict[str, Any]]] = []
    service_probe: dict[str, Any] | None = None
    results: list[tuple[str, str]] = []
    failures = 0

    try:
        _seed(service, rows, created)
        print(f"Seeded disposable fixtures for {len(ALL_TABLES)} tables.")

        # A fresh conversation proves service-role writes are live and avoids
        # confusing a duplicate-key response with a successful RLS bypass.
        service_probe = {
            **rows["conversations"],
            "id": _uuid(),
            "title": "rls-service-role-probe",
        }
        inserted = service.table("conversations").insert(service_probe).select("id").execute().data or []
        write_ok = len(inserted) == 1 and inserted[0].get("id") == service_probe["id"]
        results.append(("service role writes conversations", "ok" if write_ok else "service role insert returned no matching row"))
        read_back = service.table("conversations").select("id").match({"id": service_probe["id"]}).execute().data or []
        results.append(("service role reads its conversation", "ok" if len(read_back) == 1 else "service role could not read back its row"))

        for table in OWNED_TABLES:
            row = rows[table]
            owner_write_allowed = table not in READ_ONLY_TABLES
            owner_write_name = (
                f"user A writes own {table}"
                if owner_write_allowed
                else f"user A is refused writes to {table} (select-only)"
            )
            results.extend((
                (f"anon read {table}", _read_result(_anonymous_client(url, anon_key), table, row, should_read=False)),
                (f"anon write {table}", _update_result(_anonymous_client(url, anon_key), service, table, row, actor=uid_b, allowed=False, owner_id=uid_a)),
                (f"user B read A's {table}", _read_result(user_b, table, row, should_read=False)),
                (f"user B write A's {table}", _update_result(user_b, service, table, row, actor=uid_b, allowed=False, owner_id=uid_a)),
                (f"user A reads own {table}", _read_result(user_a, table, row, should_read=True)),
                (owner_write_name, _update_result(user_a, service, table, row, actor=uid_a, allowed=owner_write_allowed, owner_id=uid_a)),
                (f"user A cannot transfer A's {table} to user B", _update_result(user_a, service, table, row, actor=uid_b, allowed=False, owner_id=uid_a)),
            ))

        for table in BACKEND_ONLY_TABLES:
            row = rows[table]
            # Re-inserting the same primary/unique key is deliberate: with no
            # policy PostgreSQL returns 42501 before uniqueness is considered;
            # a duplicate-key error means a client write reached the table.
            for label, client in (
                ("anon", _anonymous_client(url, anon_key)),
                ("user B", user_b),
                ("user A", user_a),
            ):
                results.append((f"{label} read backend-only {table}", _read_result(client, table, row, should_read=False)))
                results.append((f"{label} write backend-only {table}", _insert_result(client, table, row, denied=True)))
    except Exception as exc:
        print(f"BLOCKED  Fixture setup/probe failed ({type(exc).__name__}): {_error_text(exc)}")
        return_code = 2
    else:
        return_code = 0
    finally:
        cleanup_errors = _cleanup(service, created, service_probe)
        if cleanup_errors:
            print("FAIL  cleanup: " + "; ".join(cleanup_errors))
            return_code = 1

    if return_code and not results:
        print("0 RLS checks completed; fixture setup did not reach the probe phase.")
        return return_code

    for name, outcome in results:
        mark = "PASS" if outcome == "ok" else "FAIL"
        print(f"{mark}  {name}" + ("" if outcome == "ok" else f" -- {outcome}"))
        if outcome != "ok":
            failures += 1

    print(f"\n{len(results) - failures}/{len(results)} checks passed")
    if failures:
        print(f"FAILURES: {failures}; inspect the named rows above.")
        return 1
    if return_code:
        return return_code
    print("RLS verified: client access is owner-scoped, backend-only tables deny clients, service role works.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
