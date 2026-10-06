"""Desktop and system actions the model can ask for.

This is deliberately *not* the shell tool. The shell classifier refuses
backgrounding and refuses ``kill``/``pkill`` outright, because a command line is
untrusted text that gets parsed by a shell. These actions are a fixed set of
named operations, each executed as an argv list with no shell anywhere in the
path, so there is nothing for the model to smuggle an extra argument into.

Every action that changes state asks the user first, by going through the same
``REGISTRY`` the shell tool uses. That means the existing approval card, the
``/api/commands/decide`` endpoint and the pending-poll in the client work
unchanged -- there is no second approval UI to keep in sync.

The window actions drive KWin through its scripting DBus interface. KWin
scripts cannot write files and cannot return a value over DBus, so a script
prints its result and we read it back out of the user journal. That round trip
is the only way to reach the compositor on Wayland: ``wmctrl`` and ``xdotool``
speak X11 and cannot see native Wayland windows.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.config import settings
from app.services.command_runner import REGISTRY, CommandResult, PendingRequest
from app.services.permissions import DEFAULT_PERMISSION_LEVEL, requires_approval

DESKTOP_TOOL_NAME = "run_desktop_action"

# Prefix for every line a KWin script prints. The journal is a shared stream, so
# each invocation carries a unique token and we only accept lines carrying it.
_SENTINEL_PREFIX = "PENTAGONWM"


def _result(
    display: str,
    *,
    stdout: str = "",
    stderr: str = "",
    exit_code: int = 0,
    auto_approved: bool = False,
    started: float | None = None,
) -> CommandResult:
    duration = 0.0 if started is None else round((time.perf_counter() - started) * 1000, 2)
    return CommandResult(
        command=display,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration,
        auto_approved=auto_approved,
    )


async def _run_argv(argv: list[str], *, timeout: float = 20.0) -> tuple[int, str, str]:
    """Run an argv list. No shell, ever -- so no quoting rules to get wrong."""
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (OSError, ValueError) as exc:
        return 127, "", f"Could not run {argv[0]!r}: {exc}"
    try:
        raw_out, raw_err = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except (TimeoutError, asyncio.TimeoutError):
        try:
            process.kill()
        except ProcessLookupError:
            pass
        return 124, "", f"{argv[0]} timed out after {timeout:.0f}s"
    return (
        process.returncode if process.returncode is not None else 1,
        raw_out.decode("utf-8", "replace"),
        raw_err.decode("utf-8", "replace"),
    )


def _spawn_detached(argv: list[str]) -> None:
    """Start a GUI app in its own session so it outlives this process.

    This is the reason the shell tool cannot open an application: ``&`` and
    ``nohup`` are backgrounding syntax, and the classifier rejects it. Here the
    separation is done properly by the kernel instead of by the command line.
    """
    subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


# --------------------------------------------------------------------------
# Turning the name a person says into something that actually starts
# --------------------------------------------------------------------------

# Where desktop entries live. Flatpak and Snap both stage their entries into a
# directory rather than /usr/share/applications, so a single-directory lookup
# misses half the installed applications.
_DESKTOP_DIRS = (
    "/usr/share/applications",
    "/var/lib/snapd/desktop/applications",
    "/var/lib/flatpak/exports/share/applications",
    "~/.local/share/applications",
    "~/.local/share/flatpak/exports/share/applications",
)

# Desktop files are cheap but not free to parse, and the model may try several
# names in one turn. Keyed by the directory tuple so tests can pass their own.
_DESKTOP_CACHE: dict[tuple[str, ...], list["_DesktopEntry"]] = {}


@dataclass(frozen=True)
class _DesktopEntry:
    desktop_id: str
    name: str
    binary: str


@dataclass(frozen=True)
class _LaunchCandidate:
    label: str
    argv: list[str]
    binary: str


def _normalise(text: str) -> str:
    """Fold a name to something worth comparing: 'Visual Studio Code' -> 'visual studio code'."""
    folded = "".join(char.lower() if char.isalnum() else " " for char in text)
    return " ".join(folded.split())


def _desktop_entries(dirs: tuple[str, ...] | None = None) -> list[_DesktopEntry]:
    """Read the installed ``.desktop`` files once.

    Only the three fields that matter here are kept: the id, the name, and the
    binary the entry starts. ``Exec`` is a command line with field codes such
    as ``%U``; only its first token identifies the process to look for later.
    """
    dirs = dirs or _DESKTOP_DIRS
    cached = _DESKTOP_CACHE.get(dirs)
    if cached is not None:
        return cached

    entries: list[_DesktopEntry] = []
    for directory in dirs:
        root = os.path.expanduser(directory)
        try:
            filenames = sorted(os.listdir(root))
        except OSError:
            continue
        for filename in filenames:
            if not filename.endswith(".desktop"):
                continue
            path = os.path.join(root, filename)
            try:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    fields: dict[str, str] = {}
                    for line in handle:
                        line = line.strip()
                        if not line or line.startswith(("#", "[")) or "=" not in line:
                            continue
                        key, _, value = line.partition("=")
                        # First spelling wins: a localised Name[de] must not
                        # overwrite the untranslated Name.
                        fields.setdefault(key.strip(), value.strip())
            except OSError:
                continue
            if fields.get("Type", "Application") != "Application":
                continue
            if fields.get("Hidden", "false").lower() == "true":
                continue
            if fields.get("NoDisplay", "false").lower() == "true":
                continue
            try_exec = fields.get("TryExec", "")
            if try_exec and not shutil.which(try_exec):
                continue
            exec_line = fields.get("Exec", "")
            binary = ""
            for token in exec_line.split():
                if token.startswith("%") or token in {"env", "sh", "bash", "/bin/sh"}:
                    continue
                binary = os.path.basename(token)
                break
            name = fields.get("Name", "").strip()
            if not name and not binary:
                continue
            entries.append(
                _DesktopEntry(
                    desktop_id=filename[: -len(".desktop")],
                    name=name or filename[: -len(".desktop")],
                    binary=binary,
                )
            )
    _DESKTOP_CACHE[dirs] = entries
    return entries


def _score_app(query: str, entry: _DesktopEntry) -> int:
    """How well an entry answers to this name. 0 means no match at all."""
    wanted = _normalise(query)
    if not wanted:
        return 0
    entry_id = _normalise(entry.desktop_id)
    entry_name = _normalise(entry.name)
    if wanted == entry_id:
        return 100
    if wanted == entry_name:
        return 95
    # "vscode" has to reach code.desktop ("Visual Studio Code"). Substring on
    # either side covers the common misspellings and abbreviations.
    if wanted in entry_id:
        return 70
    if wanted in entry_name:
        return 68
    # The other direction: what the person typed *contains* the real name. This
    # is the "vscode" -> code.desktop case, which substring matching misses
    # because the query is the longer string. Both sides must be at least four
    # characters so that a two-letter id cannot match half the desktop.
    for token in wanted.split():
        if len(token) < 4:
            continue
        if len(entry_id) >= 4 and entry_id in token:
            return 72
        if len(entry_name) >= 4 and entry_name in token:
            return 70
    if all(token in f"{entry_id} {entry_name}" for token in wanted.split()):
        return 60
    return 0


def _resolve_app(query: str, dirs: tuple[str, ...] | None = None) -> list[_LaunchCandidate]:
    """Best ways to start the application this person just named.

    Both halves matter. The desktop id is what ``gtk-launch`` and ``kioclient
    exec`` want, and the entry's own binary is what proves afterwards that
    something actually started. Handing either one the display name is what made
    ``kioclient exec vscode`` exit 0 while launching nothing at all.
    """
    ranked: list[tuple[int, _DesktopEntry]] = []
    for entry in _desktop_entries(dirs):
        score = _score_app(query, entry)
        if score:
            ranked.append((score, entry))
    ranked.sort(key=lambda pair: (-pair[0], pair[1].desktop_id))

    candidates: list[_LaunchCandidate] = []
    seen: set[str] = set()
    for _, entry in ranked[:3]:
        if entry.desktop_id in seen:
            continue
        seen.add(entry.desktop_id)
        launcher = (
            ["gtk-launch", entry.desktop_id]
            if shutil.which("gtk-launch")
            else ["kioclient", "exec", entry.desktop_id]
        )
        binary = entry.binary or entry.desktop_id
        candidates.append(_LaunchCandidate(entry.name, launcher, binary))
        # The entry's own binary is a second, independent route: it works when
        # the launcher is missing, and it is what the process check looks for.
        located = shutil.which(binary)
        if located:
            candidates.append(_LaunchCandidate(entry.name, [located], binary))

    # A binary on PATH with no desktop entry at all is still a real answer.
    located = shutil.which(query)
    if located:
        candidates.append(_LaunchCandidate(query, [located], os.path.basename(located)))
    return candidates


def _processes_named(binary: str) -> set[int]:
    """PIDs whose command name matches, read from /proc rather than by forking ps.

    Both ``comm`` and the first word of ``cmdline`` are checked. ``comm`` is the
    kernel's name and is capped at 15 characters, so ``brave-browser-stable``
    is recorded as ``brave-browser-s`` and an exact comparison against the real
    binary name would never match it.
    """
    if not binary:
        return set()
    found: set[int] = set()
    try:
        entries = os.listdir("/proc")
    except OSError:
        return found
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/comm", encoding="utf-8", errors="replace") as handle:
                if handle.read().strip() == binary:
                    found.add(int(entry))
                    continue
        except OSError:
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as handle:
                argv0 = handle.read().split(b"\0", 1)[0].decode("utf-8", "replace")
        except OSError:
            continue
        if argv0 and os.path.basename(argv0) == binary:
            found.add(int(entry))
    return found


async def _wait_for_process(binary: str, timeout: float = 3.0) -> bool:
    """Wait for proof that the app started, instead of assuming it did."""
    if not binary:
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _processes_named(binary):
            return True
        await asyncio.sleep(0.2)
    return False


async def _window_keys() -> set[tuple[str, str]]:
    """A snapshot of open windows, for telling "appeared" from "was already there".

    Best-effort: a machine with no compositor to ask simply returns nothing, and
    the caller falls back to the process check alone.
    """
    try:
        windows = await _resolve_windows("")
    except Exception:  # noqa: BLE001 - verification must never raise into the action
        return set()
    return {(window.caption, window.resource_class) for window in windows}


async def _wait_for_launch(
    candidate: _LaunchCandidate,
    before: set[tuple[str, str]],
    timeout: float = 4.0,
) -> bool:
    """Did the app actually start? A process is proof; a new window is better.

    Matching the process name alone is not enough, because a desktop entry can
    point at a wrapper: Brave's entry starts ``brave-browser-stable`` but the
    process that appears is called ``brave``. A window appearing is what the
    person actually asked for, so it counts too -- but only a window that was
    not already open, or an unrelated window that happens to share the name
    would confirm a launch that never happened.
    """
    deadline = time.monotonic() + timeout
    wanted = [
        term
        for term in (_normalise(candidate.label), _normalise(candidate.binary))
        if len(term) >= 4
    ]
    while time.monotonic() < deadline:
        if _processes_named(candidate.binary):
            return True
        if wanted:
            try:
                windows = await _resolve_windows("")
            except Exception:  # noqa: BLE001
                windows = []
            for window in windows:
                key = (window.caption, window.resource_class)
                if key in before:
                    continue
                haystack = f"{_normalise(window.caption)} {_normalise(window.resource_class)}"
                if any(term in haystack for term in wanted):
                    return True
        await asyncio.sleep(0.25)
    return False


# --------------------------------------------------------------------------
# KWin window management
# --------------------------------------------------------------------------

_KWIN_JS_PREAMBLE = """
function __pwWindows() {
    if (workspace.windowList) { return workspace.windowList(); }
    if (workspace.stackingOrder) { return workspace.stackingOrder(); }
    return workspace.clientList();
}
function __pwEmit(line) { print("%(token)s|" + line); }
"""


async def _kwin(script_body: str, *, timeout: float = 10.0) -> list[str]:
    """Evaluate a KWin script and return the lines it emitted.

    The script is written to a temp file, handed to KWin over DBus, and its
    ``print()`` output is read back from the user journal. Anything printed
    without our token is ignored, so concurrent output cannot be mistaken for
    our answer.
    """
    if not shutil.which("qdbus6"):
        return ["Window control needs qdbus6 (from KDE), which is not installed."]
    if not shutil.which("journalctl"):
        return ["Window control needs journalctl, which is not installed."]

    token = f"{_SENTINEL_PREFIX}{uuid.uuid4().hex[:12]}"
    plugin = f"pentagon_{token[-10:]}"
    source = _KWIN_JS_PREAMBLE % {"token": token} + script_body
    handle, path = tempfile.mkstemp(prefix=token, suffix=".js", text=True)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as script_file:
            script_file.write(source)
        marker = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 1))
        exit_code, _, err = await _run_argv(
            [
                "qdbus6", "org.kde.KWin", "/Scripting",
                "org.kde.kwin.Scripting.loadScript", path, plugin,
            ],
            timeout=timeout,
        )
        if exit_code != 0:
            return [f"KWin refused the script: {err.strip() or exit_code}"]
        await _run_argv(
            ["qdbus6", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.start"],
            timeout=timeout,
        )

        deadline = time.monotonic() + timeout
        lines: list[str] = []
        while time.monotonic() < deadline:
            await asyncio.sleep(0.4)
            exit_code, out, _ = await _run_argv(
                ["journalctl", "--user", "-o", "cat", "--since", marker, "--no-pager"],
                timeout=timeout,
            )
            if exit_code != 0:
                return ["Could not read the user journal, so window control has no result."]
            for line in out.splitlines():
                marker_at = line.find(f"{token}|")
                if marker_at >= 0:
                    lines.append(line[marker_at + len(token) + 1:])
            if any(item == "__END__" for item in lines):
                break
        return lines or ["The window manager did not answer in time."]
    finally:
        await _run_argv(
            ["qdbus6", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.unloadScript", plugin],
            timeout=5,
        )
        try:
            os.unlink(path)
        except OSError:
            pass


def _js_string(value: str) -> str:
    """A JS string literal for an arbitrary target, without injection."""
    return json.dumps(value)


def _windows_script(operation: str, needle: str = "") -> str:
    return f"""
try {{
    const operation = {_js_string(operation)};
    const wanted = {_js_string(needle)};
    const windows = __pwWindows();
    const matches = windows.filter(function (w) {{
        if (!w) {{ return false; }}
        if (!wanted) {{ return true; }}
        const caption = w.caption || "";
        const resource = w.resourceClass || "";
        const desktop = w.desktopFile || "";
        return caption.toLowerCase().indexOf(wanted.toLowerCase()) >= 0
            || resource.toLowerCase().indexOf(wanted.toLowerCase()) >= 0
            || desktop.toLowerCase().indexOf(wanted.toLowerCase()) >= 0;
    }});

    if (operation === "list") {{
        __pwEmit("count=" + matches.length);
        for (const w of matches) {{
            __pwEmit("window\\t" + (w.caption || "(untitled)") + "\\t" + (w.resourceClass || "-") + "\\t" + (w.desktopFile || "-"));
        }}
    }} else if (operation === "closeAll") {{
        if (matches.length === 0) {{
            __pwEmit("no-match");
        }} else {{
            for (const w of matches) {{
                __pwEmit("matched=" + (w.caption || "(untitled)"));
                try {{ w.closeWindow(); }} catch (e) {{ __pwEmit("refused=" + (w.caption || "?")); }}
            }}
            __pwEmit("closed-count=" + matches.length);
        }}
    }} else {{
        if (matches.length === 0) {{
            __pwEmit("no-match");
        }} else {{
            const target = matches[0];
            __pwEmit("matched=" + (target.caption || "(untitled)"));
            if (matches.length > 1) {{ __pwEmit("also-matched=" + (matches.length - 1)); }}
            if (operation === "focus") {{ workspace.activeWindow = target; }}
            else {{ target.closeWindow(); }}
        }}
    }}
}} catch (e) {{
    __pwEmit("error:" + String(e).slice(0, 200));
}}
__pwEmit("__END__");
"""


# --------------------------------------------------------------------------
# Action handlers
# --------------------------------------------------------------------------

Handler = Callable[[dict[str, Any]], Awaitable[CommandResult]]


def _clean_app_name(raw: str) -> str | None:
    """Accept only something that can be an application name, never a command line.

    Nothing here is executed through a shell, so a ``;`` would be a literal
    character rather than a separator. Rejecting it anyway means a name that
    looks like an injection attempt fails loudly instead of launching an
    application with a strange name. Spaces stay allowed, because application
    names genuinely contain them ("Google Chrome").
    """
    name = (raw or "").strip()
    if not name or len(name) > 120:
        return None
    if any(char in name for char in ";&|<>()$`\\/*?[]{}!#~'\"\n\r\t"):
        return None
    return name


def _safe_url(raw: str) -> str | None:
    """Only http(s). ``file:``, ``javascript:`` and ``data:`` are injection paths."""
    url = (raw or "").strip()
    if len(url) > 2000:
        return None
    lowered = url.lower()
    if lowered.startswith(("http://", "https://")):
        return url
    return None


@dataclass(frozen=True)
class Window:
    """One open window, as the compositor sees it."""

    caption: str
    resource_class: str
    desktop_file: str


def _parse_window_rows(lines: list[str]) -> list[Window]:
    windows: list[Window] = []
    for line in lines:
        if not line.startswith("window\t"):
            continue
        parts = line.split("\t")
        caption = parts[1] if len(parts) > 1 else ""
        resource = parts[2] if len(parts) > 2 else "-"
        desktop = parts[3] if len(parts) > 3 else "-"
        windows.append(
            Window(
                caption=caption or "(untitled)",
                resource_class="" if resource == "-" else resource,
                desktop_file="" if desktop == "-" else desktop,
            )
        )
    return windows


async def _resolve_windows(needle: str) -> list[Window]:
    """Find the windows a needle matches. Read-only, so it runs before asking."""
    lines = await _kwin(_windows_script("list", needle))
    return _parse_window_rows(lines)


def _describe_windows(windows: list[Window]) -> str:
    """The 'this is what will happen' line shown on the approval card."""
    if not windows:
        return ""
    if len(windows) == 1:
        window = windows[0]
        app = window.resource_class or window.desktop_file
        return f'"{window.caption}"' + (f" ({app})" if app else "")
    listed = "; ".join(f'"{window.caption}"' for window in windows[:6])
    if len(windows) > 6:
        listed += f"; and {len(windows) - 6} more"
    return f"{len(windows)} windows: {listed}"


async def _action_list_windows(args: dict[str, Any]) -> CommandResult:
    display = "List the open windows"
    needle = str(args.get("target") or "").strip()
    lines = await _kwin(_windows_script("list", needle))
    rows = [line for line in lines if line.startswith("window\t")]
    if not rows and lines and lines[0].startswith("error:"):
        return _result(display, stderr=lines[0], exit_code=1)
    if not rows:
        return _result(display, stdout="\n".join(lines) or "No windows matched.")
    header = f"{len(rows)} window(s):" + (f" matching {needle!r}" if needle else "")
    body = "\n".join(row.replace("\t", " | ") for row in rows)
    return _result(display, stdout=f"{header}\n{body}")


def _resolved_windows(args: dict[str, Any]) -> list[Window]:
    """The windows the dispatcher already resolved before asking."""
    found = args.get("_resolved")
    return found if isinstance(found, list) else []


async def _one_window(args: dict[str, Any], *, verb: str) -> tuple[Window | None, CommandResult | None]:
    """The single window this action targets.

    The dispatcher has already resolved it and refused an ambiguous match, so
    by the time we get here there is exactly one, and it is the one the user
    was shown.
    """
    windows = _resolved_windows(args)
    if not windows:
        return None, _result(
            f"{verb} a window",
            stderr="The target window was not resolved before this ran.",
            exit_code=1,
        )
    return windows[0], None


async def _action_focus_window(args: dict[str, Any]) -> CommandResult:
    window, failure = await _one_window(args, verb="Focus")
    if failure is not None:
        return failure
    assert window is not None
    lines = await _kwin(_windows_script("focus", window.caption))
    if "matched=" not in "\n".join(lines):
        return _result(
            f"Focus the window: {window.caption}",
            stderr="\n".join(lines),
            exit_code=1,
        )
    return _result(f"Focus the window: {window.caption}",
                   stdout=f"Brought {window.caption} to the front.")


async def _action_close_window(args: dict[str, Any]) -> CommandResult:
    window, failure = await _one_window(args, verb="Close")
    if failure is not None:
        return failure
    assert window is not None
    # Target the resolved caption, not the original needle, so exactly the
    # window the user was shown is the one that closes.
    lines = await _kwin(_windows_script("close", window.caption))
    if "matched=" not in "\n".join(lines):
        return _result(
            f"Close the window: {window.caption}",
            stderr="\n".join(lines),
            exit_code=1,
        )
    return _result(f"Close the window: {window.caption}",
                   stdout=f"Asked {window.caption} to close.")


async def _action_open_app(args: dict[str, Any]) -> CommandResult:
    name = _clean_app_name(str(args.get("target") or ""))
    display = f"Open the application {str(args.get('target') or '')!r}"
    if not name:
        return _result(
            display,
            stderr=(
                "That is not a usable application name. Give one word such as "
                "firefox or code, not a path and not a command line."
            ),
            exit_code=1,
        )

    candidates = _resolve_app(name)
    if not candidates:
        return _result(
            display,
            stderr=(
                f"No installed application matches {name!r}. Look under "
                "/usr/share/applications for the real name, or ask the user what "
                "to call it."
            ),
            exit_code=1,
        )

    errors: list[str] = []
    for candidate in candidates:
        already = _processes_named(candidate.binary)
        before = await _window_keys()
        try:
            _spawn_detached(candidate.argv)
        except OSError as exc:
            errors.append(f"{candidate.label}: {exc}")
            continue
        if already:
            return _result(
                display,
                stdout=(
                    f"{candidate.label} was already running, so it was asked to "
                    "open a new window instead of starting again."
                ),
            )
        if await _wait_for_launch(candidate, before):
            return _result(display, stdout=f"Launched {candidate.label}.")
        errors.append(f"{candidate.label}: nothing started")
    return _result(
        display,
        stderr=(
            f"Could not start {name}. "
            + ("; ".join(errors) or "Nothing matched.")
            + " Try the application's real name."
        ),
        exit_code=1,
    )


async def _action_open_url(args: dict[str, Any]) -> CommandResult:
    url = _safe_url(str(args.get("target") or ""))
    display = f"Open the URL {str(args.get('target') or '')!r}"
    if not url:
        return _result(
            display,
            stderr="Only http:// and https:// URLs are allowed.",
            exit_code=1,
        )
    try:
        _spawn_detached(["xdg-open", url])
    except OSError as exc:
        return _result(display, stderr=f"Could not open the URL: {exc}", exit_code=1)
    return _result(display, stdout=f"Opened {url} in the default browser.")


async def _action_open_path(args: dict[str, Any]) -> CommandResult:
    raw = str(args.get("target") or "").strip()
    display = f"Open {raw!r} in the file manager"
    if not raw:
        return _result(display, stderr="No path was given.", exit_code=1)
    target = raw if "://" in raw else f"file://{os.path.abspath(os.path.expanduser(raw))}"
    if not target.startswith("file://"):
        return _result(display, stderr="Only local paths are allowed here.", exit_code=1)
    path = target[len("file://"):] or "/"
    if not os.path.exists(path):
        return _result(display, stderr=f"{path} does not exist.", exit_code=1)
    try:
        _spawn_detached(["kioclient", "exec", target])
    except OSError as exc:
        return _result(display, stderr=f"Could not open the file manager: {exc}", exit_code=1)
    return _result(display, stdout=f"Opened {path}.")


async def _action_close_app(args: dict[str, Any]) -> CommandResult:
    """Close every window belonging to an application.

    This asks the windows to close, which is what a user clicking the X does.
    It deliberately does not signal a process: an app that keeps running in the
    tray is reported honestly rather than killed behind the user's back.
    """
    needle = str(args.get("target") or "").strip()
    windows = _resolved_windows(args)
    if not windows:
        return _result(
            f"Close the application {needle!r}",
            stderr="The target windows were not resolved before this ran.",
            exit_code=1,
        )
    captions = [window.caption for window in windows]
    lines = await _kwin(_windows_script("closeAll", needle))
    refused = [
        line.split("refused=", 1)[1].strip()
        for line in lines
        if line.startswith("refused=")
    ]
    note = f" {len(refused)} window(s) refused to close: {', '.join(refused)}." if refused else ""
    return _result(
        f"Close the application {needle!r}",
        stdout=f"Asked {len(captions)} window(s) to close: {'; '.join(captions)}.{note}",
    )


def _desktop_file_path(raw: str) -> str | None:
    """Resolve a .desktop entry to a real file inside a trusted applications dir.

    The file is handed to KIO, which will execute it, so an arbitrary path must
    not be accepted -- otherwise "open this file" becomes "run this script".
    """
    candidate = (raw or "").strip()
    if not candidate or len(candidate) > 400:
        return None
    if not candidate.endswith(".desktop"):
        return None
    if not os.path.isabs(candidate):
        expanded = os.path.expanduser(candidate)
        roots = (
            os.path.join(os.path.expanduser("~"), ".local/share/applications"),
            "/usr/local/share/applications",
            "/usr/share/applications",
        )
        for root in roots:
            if expanded.startswith(root + os.sep):
                candidate = expanded
                break
        else:
            return None
    if not candidate.startswith("/"):
        return None
    for root in (
        os.path.join(os.path.expanduser("~"), ".local/share/applications"),
        "/usr/local/share/applications",
        "/usr/share/applications",
    ):
        if candidate.startswith(root + os.sep):
            break
    else:
        return None
    return candidate if os.path.isfile(candidate) else None


async def _action_launch_desktop_file(args: dict[str, Any]) -> CommandResult:
    raw = str(args.get("target") or "").strip()
    display = f"Launch the application entry {raw!r}"
    path = _desktop_file_path(raw)
    if path is None:
        return _result(
            display,
            stderr=(
                "That is not a .desktop file inside your applications folder "
                "(~/.local/share/applications or /usr/share/applications)."
            ),
            exit_code=1,
        )
    try:
        _spawn_detached(["kioclient", "exec", path])
    except OSError as exc:
        return _result(display, stderr=f"Could not launch it: {exc}", exit_code=1)
    return _result(display, stdout=f"Launched {os.path.basename(path)}.")


async def _action_screenshot(args: dict[str, Any]) -> CommandResult:
    raw = str(args.get("target") or "").strip()
    display = "Take a screenshot"
    directory = settings.screenshot_directory or tempfile.gettempdir()
    try:
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, raw) if raw else os.path.join(
            directory, f"pentagon-{time.strftime('%Y%m%d-%H%M%S')}.png"
        )
    except OSError as exc:
        return _result(display, stderr=f"Could not use {directory!r}: {exc}", exit_code=1)
    if os.path.isdir(path):
        path = os.path.join(path, f"pentagon-{time.strftime('%Y%m%d-%H%M%S')}.png")
    if not shutil.which("spectacle"):
        return _result(display, stderr="Screenshots need spectacle (KDE), which is not installed.", exit_code=1)
    exit_code, _, err = await _run_argv(
        ["spectacle", "-b", "-n", "-f", "-o", path], timeout=40
    )
    if exit_code != 0 or not os.path.exists(path):
        return _result(display, stderr=err.strip() or f"exited {exit_code}", exit_code=1)
    return _result(display, stdout=f"Saved a screenshot to {path}.")


async def _action_volume(args: dict[str, Any]) -> CommandResult:
    what = str(args.get("target") or "get").strip().lower() or "get"
    display = f"Audio volume: {what}"
    if not shutil.which("pactl"):
        return _result(display, stderr="Volume control needs pactl, which is not installed.", exit_code=1)
    if what == "get":
        exit_code, out, err = await _run_argv(
            ["pactl", "get-sink-volume", "@DEFAULT_SINK@"], timeout=10
        )
        return _result(display, stdout=out.strip(), stderr=err.strip(), exit_code=exit_code)
    commands = {
        "up": ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+5%"],
        "down": ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-5%"],
        "up_big": ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+15%"],
        "down_big": ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-15%"],
        "mute": ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"],
        "unmute": ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"],
    }
    if what == "toggle":
        exit_code, state, _ = await _run_argv(
            ["pactl", "get-sink-mute", "@DEFAULT_SINK@"], timeout=10
        )
        muted = "yes" in state.lower()
        what = "unmute" if muted else "mute"
    if what not in commands:
        return _result(display, stderr=f"Unknown volume action {what!r}.", exit_code=1)
    exit_code, _, err = await _run_argv(commands[what], timeout=10)
    if exit_code != 0:
        return _result(display, stderr=err.strip(), exit_code=exit_code)
    exit_code, state, _ = await _run_argv(
        ["pactl", "get-sink-mute", "@DEFAULT_SINK@"], timeout=10
    )
    exit_code, volume, _ = await _run_argv(
        ["pactl", "get-sink-volume", "@DEFAULT_SINK@"], timeout=10
    )
    suffix = " (muted)" if "yes" in state.lower() else ""
    return _result(display, stdout=f"Volume is now {volume.strip()}{suffix}.")


async def _action_media(args: dict[str, Any]) -> CommandResult:
    what = str(args.get("target") or "play").strip().lower()
    display = f"Media control: {what}"
    verbs = {"play": "Play", "pause": "Pause", "playpause": "PlayPause",
             "next": "Next", "previous": "Previous", "stop": "Stop"}
    verb = verbs.get(what)
    if verb is None:
        return _result(display, stderr=f"Unknown media action {what!r}.", exit_code=1)
    exit_code, out, err = await _run_argv(
        ["qdbus6", "-l"], timeout=10
    )
    players: list[str] = []
    if exit_code == 0:
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("org.mpris.MediaPlayer2."):
                players.append(line)
    if not players:
        return _result(
            display,
            stderr="No MPRIS media player is running, so there is nothing to control.",
            exit_code=1,
        )
    for player in players:
        exit_code, _, _ = await _run_argv(
            ["qdbus6", player, "/org/mpris/MediaPlayer2", f"org.mpris.MediaPlayer2.Player.{verb}"],
            timeout=10,
        )
        if exit_code == 0:
            return _result(display, stdout=f"Sent {verb} to {player.split('.')[-1]}.")
    return _result(display, stderr="Every MPRIS player refused that command.", exit_code=1)


async def _action_notify(args: dict[str, Any]) -> CommandResult:
    title = str(args.get("target") or "Pentagon").strip()[:80] or "Pentagon"
    body = str(args.get("body") or "").strip()[:400]
    display = f"Show a notification titled {title!r}"
    argv = ["notify-send", title]
    if body:
        argv.append(body)
    exit_code, _, err = await _run_argv(argv, timeout=10)
    return _result(display, stderr=err.strip(), exit_code=exit_code) if exit_code else _result(
        display, stdout="Notification sent."
    )


async def _action_lock(args: dict[str, Any]) -> CommandResult:
    display = "Lock the screen"
    exit_code, _, err = await _run_argv(
        ["qdbus6", "org.freedesktop.ScreenSaver", "/ScreenSaver",
         "org.freedesktop.ScreenSaver.Lock"],
        timeout=15,
    )
    if exit_code != 0:
        exit_code, _, err = await _run_argv(["loginctl", "lock-session"], timeout=15)
    return _result(display, stderr=err.strip(), exit_code=exit_code) if exit_code else _result(
        display, stdout="Screen locked."
    )


async def _action_dark_mode(args: dict[str, Any]) -> CommandResult:
    what = str(args.get("target") or "toggle").strip().lower()
    display = f"Dark mode: {what}"
    looks = ["BreezeDark", "Breeze", "NordicDark", "Nordic"]
    try:
        if what in ("on", "dark", "enable"):
            argv = ["plasma-apply-lookandfeel", "--dark"]
        elif what in ("off", "light", "disable"):
            argv = ["plasma-apply-lookandfeel", "--light"]
        elif what == "toggle":
            argv = ["plasma-apply-lookandfeel", "--dark"]
        else:
            return _result(display, stderr=f"Unknown dark mode action {what!r}.", exit_code=1)
        if not shutil.which(argv[0]):
            argv = ["plasma-apply-colorscheme", looks[0] if what != "off" else looks[1]]
        exit_code, _, err = await _run_argv(argv, timeout=25)
    except OSError as exc:
        return _result(display, stderr=f"Could not change the theme: {exc}", exit_code=1)
    if exit_code != 0:
        return _result(display, stderr=err.strip(), exit_code=exit_code)
    return _result(display, stdout=f"Applied {what} mode.")


async def _action_power(args: dict[str, Any]) -> CommandResult:
    what = str(args.get("target") or "").strip().lower()
    display = f"Power: {what}"
    table = {
        "suspend": ["systemctl", "suspend"],
        "sleep": ["systemctl", "suspend"],
        "hibernate": ["systemctl", "hibernate"],
        "shutdown": ["systemctl", "poweroff"],
        "reboot": ["systemctl", "reboot"],
    }
    argv = table.get(what)
    if argv is None:
        return _result(
            display,
            stderr="Choose one of: suspend, hibernate, shutdown, reboot.",
            exit_code=1,
        )
    exit_code, _, err = await _run_argv(argv, timeout=25)
    return _result(display, stdout=f"Asked the system to {what}.") if exit_code == 0 else _result(
        display, stderr=err.strip(), exit_code=exit_code
    )


async def _action_system_info(args: dict[str, Any]) -> CommandResult:
    display = "Read the desktop session details"
    rows: list[str] = []
    for key, label in (
        ("XDG_CURRENT_DESKTOP", "Desktop"),
        ("XDG_SESSION_TYPE", "Session type"),
    ):
        value = os.environ.get(key)
        if value and value not in [row.split(":", 1)[1] for row in rows]:
            rows.append(f"{label}: {value}")
    exit_code, out, _ = await _run_argv(["pactl", "info"], timeout=10)
    if exit_code == 0:
        for line in out.splitlines():
            if line.startswith(("Sink:", "Source:", "Server:", "Default Sink:")):
                rows.append(line.strip())
    return _result(display, stdout="\n".join(rows) or "Not enough environment to describe.")


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DesktopAction:
    """One named, fixed operation. ``changes_state`` drives the approval gate."""

    name: str
    description: str
    target_hint: str
    handler: Handler
    changes_state: bool = True
    # Whether this action's worst case is unrecoverable rather than merely
    # unwanted. Only consulted at the Trusted level, where ordinary
    # state-changes run unattended and this tail still stops to ask.
    destructive: bool = False
    # Optional pure check run *before* the user is asked. An action whose
    # argument is impossible to satisfy should not put a card on screen and
    # then fail anyway; this returns an error message, or None if fine.
    validate: Callable[[dict[str, Any]], str | None] | None = None

    @property
    def needs_approval(self) -> bool:
        return self.changes_state

    def display(self, args: dict[str, Any]) -> str:
        target = str(args.get("target") or "").strip()
        return f"{self.description}: {target}" if target else self.description


ACTIONS: dict[str, DesktopAction] = {
    action.name: action
    for action in (
        DesktopAction(
            "list_windows",
            "List the windows that are open",
            "optional substring to filter by",
            _action_list_windows,
            changes_state=False,
        ),
        DesktopAction(
            "system_info",
            "Read the desktop session and audio details",
            "ignored",
            _action_system_info,
            changes_state=False,
        ),
        DesktopAction(
            "open_app",
            "Open an application",
            "the application name, one word",
            _action_open_app,
        ),
        DesktopAction(
            "open_url",
            "Open a web address in the default browser",
            "an http:// or https:// address",
            _action_open_url,
        ),
        DesktopAction(
            "open_path",
            "Open a file or folder in the file manager",
            "the path",
            _action_open_path,
        ),
        DesktopAction(
            "focus_window",
            "Bring an open window to the front",
            "part of the window title",
            _action_focus_window,
        ),
        DesktopAction(
            "close_window",
            "Close an open window",
            "part of the window title",
            _action_close_window,
        ),
        DesktopAction(
            "close_app",
            "Close every window of an application",
            "the application name or part of a window title",
            _action_close_app,
        ),
        DesktopAction(
            "launch_desktop_file",
            "Launch a specific .desktop application entry",
            "the path to a .desktop file in your applications folder",
            _action_launch_desktop_file,
        ),
        DesktopAction(
            "screenshot",
            "Take a screenshot of the screen",
            "optional file name",
            _action_screenshot,
        ),
        DesktopAction(
            "volume",
            "Read or change the audio volume",
            "get, up, down, up_big, down_big, mute, unmute or toggle",
            _action_volume,
        ),
        DesktopAction(
            "media",
            "Control music or video playback",
            "play, pause, playpause, next, previous or stop",
            _action_media,
        ),
        DesktopAction(
            "notify",
            "Show a notification on the desktop",
            "the notification title",
            _action_notify,
        ),
        DesktopAction(
            "lock_screen",
            "Lock the screen",
            "ignored",
            _action_lock,
        ),
        DesktopAction(
            "dark_mode",
            "Switch the desktop between dark and light",
            "on, off or toggle",
            _action_dark_mode,
        ),
        DesktopAction(
            "power",
            "Suspend, hibernate, shut down or reboot the machine",
            "suspend, hibernate, shutdown or reboot",
            _action_power,
            # Ending a session is the one thing here the user cannot undo,
            # so it keeps asking even when everything else runs unattended.
            destructive=True,
        ),
    )
}

# The read-only pair is what may run unattended. Everything else shows the
# user the approval card first, which is the whole point of this feature.
AUTO_APPROVED_ACTIONS = frozenset(
    name for name, action in ACTIONS.items() if not action.needs_approval
)

# Actions whose approval card should name the windows they resolved.
WINDOW_ACTIONS = frozenset({"focus_window", "close_window", "close_app"})

# Of those, the ones that must resolve to exactly one window. "close every
# window of this app" is meant to have many; "close this window" is not.
SINGLE_WINDOW_ACTIONS = frozenset({"focus_window", "close_window"})


def _require(what: str, allowed: frozenset[str]) -> Callable[[dict[str, Any]], str | None]:
    """A validator for an enumerated argument."""

    def check(args: dict[str, Any]) -> str | None:
        value = str(args.get("target") or "").strip().lower()
        if value not in allowed:
            return f"{what} must be one of: {', '.join(sorted(allowed))}."
        return None

    return check


def _check_url(args: dict[str, Any]) -> str | None:
    if _safe_url(str(args.get("target") or "")) is None:
        return "Only http:// and https:// URLs are allowed."
    return None


def _check_app(args: dict[str, Any]) -> str | None:
    if _clean_app_name(str(args.get("target") or "")) is None:
        return (
            "That is not a usable application name. Give one word such as firefox "
            "or code, not a path and not a command line."
        )
    return None


def _check_desktop_file(args: dict[str, Any]) -> str | None:
    if _desktop_file_path(str(args.get("target") or "")) is None:
        return (
            "That is not a .desktop file inside your applications folder "
            "(~/.local/share/applications or /usr/share/applications)."
        )
    return None


# Attached after the table is built, because these validators refer to the
# helpers the handlers themselves use.
_VALIDATORS: dict[str, Callable[[dict[str, Any]], str | None]] = {
    "open_url": _check_url,
    "open_app": _check_app,
    "launch_desktop_file": _check_desktop_file,
    "power": _require("A power action", frozenset({"suspend", "sleep", "hibernate", "shutdown", "reboot"})),
    "media": _require("A media action", frozenset({"play", "pause", "playpause", "next", "previous", "stop"})),
    "dark_mode": _require("A dark mode action", frozenset({"on", "off", "toggle", "dark", "light", "enable", "disable"})),
    "volume": _require(
        "A volume action",
        frozenset({"get", "up", "down", "up_big", "down_big", "mute", "unmute", "toggle"}),
    ),
}
ACTIONS.update({
    name: dataclasses.replace(ACTIONS[name], validate=validator)
    for name, validator in _VALIDATORS.items()
    if name in ACTIONS
})

DESKTOP_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": DESKTOP_TOOL_NAME,
        "description": (
            "Control the user's desktop: open and close applications, focus "
            "windows, take screenshots, change the volume, control playback, "
            "send notifications, lock the screen, switch dark mode, and manage "
            "power. Listing windows and reading session details run "
            "immediately; everything else is shown to the user for approval "
            "first and does nothing if they decline. Find the exact window "
            "title with list_windows before closing or focusing one."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": sorted(ACTIONS),
                    "description": "Which action to take.",
                },
                "target": {
                    "type": "string",
                    "description": "The argument for the action; see each action's hint.",
                },
                "reason": {
                    "type": "string",
                    "description": "One short sentence on why this is needed.",
                },
            },
            "required": ["action"],
        },
    },
}


def action_names() -> list[str]:
    return sorted(ACTIONS)


async def run_desktop_action(
    action: str,
    arguments: dict[str, Any] | None,
    *,
    conversation_id: str,
    user_id: str,
    reason: str = "",
    permission_level: object = DEFAULT_PERMISSION_LEVEL,
) -> CommandResult:
    """Look up an action, gate it, and run it.

    Which actions stop for the user is decided by ``services.permissions`` from
    the user's chosen level and whether the action changes state or is
    destructive. The default is Balanced, so a caller that forgets to pass a
    level gets today's behaviour rather than a silent loosening.
    """
    arguments = dict(arguments or {})
    # Keys the dispatcher injects for itself. The model's arguments are
    # untrusted, so anything underscore-prefixed is dropped before it can be
    # mistaken for resolved state.
    for key in [k for k in arguments if k.startswith("_")]:
        arguments.pop(key)
    entry = ACTIONS.get(action)
    if entry is None:
        return _result(
            f"Unknown desktop action {action!r}",
            stderr=f"Valid actions are: {', '.join(action_names())}.",
            exit_code=1,
        )

    display = entry.display(arguments)
    # `auto_approved` reports what actually happened, so it is derived from the
    # same decision the gate makes rather than from the static read-only set --
    # otherwise a Trusted user's approved-and-run action would still be logged
    # as if it had asked.
    detail = ""

    # Refuse an impossible request without troubling the user for it. Nothing
    # has run at this point, so this is safe to do ahead of the gate.
    if entry.validate is not None:
        problem = entry.validate(arguments)
        if problem is not None:
            return _result(display, stderr=problem, exit_code=1)

    # Resolve the target read-only *before* asking. This does two jobs: it names
    # the concrete thing on the card, and it refuses an ambiguous or impossible
    # target outright. Checking after the gate would mean putting a question on
    # screen for something that is then going to refuse.
    if action in WINDOW_ACTIONS:
        needle = str(arguments.get("target") or "").strip()
        windows = await _resolve_windows(needle) if needle else []
        if not windows:
            return _result(
                display,
                stderr=(
                    f"No open window matches {needle!r}. Call list_windows to see "
                    f"the real titles, then retry with an exact one."
                ),
                exit_code=1,
            )
        # close_app means "all of them", so several matches is the point. The
        # single-window actions must not guess which one was meant.
        if action in SINGLE_WINDOW_ACTIONS and len(windows) > 1:
            listed = "\n".join(
                f"  - {window.caption} [{window.resource_class or window.desktop_file or '?'}]"
                for window in windows[:10]
            )
            return _result(
                display,
                stderr=(
                    f"{needle!r} matches {len(windows)} windows, so nothing was done. "
                    f"Retry with an exact title:\n{listed}"
                ),
                exit_code=1,
            )
        detail = _describe_windows(windows)
        arguments["_resolved"] = windows

    if requires_approval(
        changes_state=entry.needs_approval,
        level=permission_level,
        destructive=entry.destructive,
    ):
        auto_approved = False
        pending = PendingRequest(
            request_id=uuid.uuid4().hex,
            conversation_id=conversation_id,
            user_id=user_id,
            command=display,
            reason=reason or entry.description,
            created_at=time.time(),
            detail=detail,
        )
        REGISTRY.submit(pending)
        approved = await REGISTRY.wait(
            pending, settings.desktop_action_approval_timeout_seconds
        )
        if not approved:
            return _result(
                display,
                stderr="The user did not approve this action, so nothing was changed.",
                exit_code=None,
                auto_approved=False,
            )
    else:
        # No question needed at this level: it runs unattended.
        auto_approved = True

    started = time.perf_counter()
    result = await entry.handler(arguments)
    result.command = display
    result.auto_approved = auto_approved
    if started is not None:
        result.duration_ms = round((time.perf_counter() - started) * 1000, 2)
    return result