"""Let the model run CLI commands, with a deliberate gate in front of them.

The design answers one question: *when may a command run without asking?* Only
when every part of it is provably read-only. Everything else is queued as a
pending request that the client has to approve, so the model's idea of a turn
never becomes a side effect the user did not agree to.

That gate is a parser, not a blocklist. An allowlist of *executables* alone
would be useless, because ``cat`` and ``rm`` are both just a name at the front
of a string, and ``ls; rm -rf ~`` is one command as far as the shell is
concerned. So the whole line is tokenised, split on the operators that chain
separate commands, and every resulting command must independently qualify.
Substitution (``$(...)``, backticks), redirection, and globbing all disqualify
a command, because those move the actual work somewhere the parser did not
look: ``ls $(cat /etc/shadow)`` never runs ``cat``, it runs *what cat printed*.

The same reasoning applies to the read-only set. ``git status`` reads; ``git
push`` writes and reaches the network. ``sed`` without ``-i`` reads; with it,
every file in the tree changes. So the allowlist is keyed on the full argv
shape, not the binary.

Nothing here is a sandbox. The user's decision was to allow the full shell as
their own user, so the allowlist decides only what may run *unattended*; an
approved command has the same power as typing it in a terminal, because at that
point the user has read it and said yes. Two hard rails hold regardless of
approval: no ``sudo``, and no shell-level escape into a decision we did not
make.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shlex
from dataclasses import dataclass, field
from typing import Any

from app.config import settings


logger = logging.getLogger(__name__)

# Characters that make the real work happen somewhere the parser cannot see:
# command substitution, redirection into a file, backgrounding, and globbing
# Constructors that make the real work happen somewhere the parser cannot see:
# command substitution, redirection, backgrounding, and globbing (a glob that
# expands to nothing becomes a literal, and one that expands to many becomes an
# argv the parser never inspected).
_SUBSTITUTION = re.compile(r"\$\(|`")
_REDIRECT_OR_BACKGROUND = re.compile(r"[<>&]")
_GLOB_OR_EXPANSION = re.compile(r"[*?\[\]{}]")
# `~` and `$` expand into paths and values the parser never sees. `~` reaches
# the home directory; `$VAR` reaches anything in the environment, which is where
# the API keys live.
_HOME_OR_VARIABLE = re.compile(r"[~$]")

# Reading is safe for the *system* but not for the *user*: the output of a
# command goes to a language model, so `cat ~/.ssh/id_rsa` is a credential
# exfiltration even though it changes nothing on disk. Anything that looks like
# a secret is treated as needing approval, however read-only the command is.
#
# Matched per path segment, so `server.pem` and `keys/id_rsa` are both caught
# while `permalink.md` and `tokens.md` are not.
_SENSITIVE_SEGMENTS = frozenset({
    "shadow", "passwd", "credentials", "secret", "secrets", "token", "tokens",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "master.key",
    ".netrc", ".npmrc", ".pypirc", ".git-credentials", ".htpasswd",
    ".ssh", ".aws", ".gnupg", ".kube", ".docker", ".azure", ".gcloud",
})
_SENSITIVE_PREFIXES = (".env", ".pem", ".key", ".p12", ".pfx", ".keystore", ".jks")
_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore")

# Operators that chain genuinely separate commands. Each side has to qualify on
# its own -- ``ls | grep x`` is fine, ``ls | sh`` is not.
_CHAIN_OPERATORS = re.compile(r"\|\||&&|\||;|\n")

# Never runs, even with approval: these escalate, and "full shell as your user"
# already excludes privilege escalation by definition.
_FORBIDDEN = frozenset({"sudo", "doas", "pkexec", "su", "runuser", "setpriv"})

# Commands that only ever read. Anything that mutates the filesystem, changes
# configuration, starts a daemon, or reaches the network is deliberately absent.
#
# Note what is *not* here despite being extremely useful: ``python3``,
# ``node``, ``make``, ``cargo``, ``pytest``, ``tsc``. Each of those executes
# arbitrary code or emits build output, so none of them is provably read-only
# and all of them ask. That is the cost of an honest allowlist: the first run
# of a build needs one click, and every run after that is the same click.
_READ_ONLY = frozenset({
    "ls", "pwd", "cat", "head", "tail", "wc", "file", "stat", "du", "df",
    "tree", "find", "grep", "egrep", "fgrep", "rg", "diff", "cmp",
    "which", "type", "whereis", "whoami", "id", "groups", "hostname",
    "uname", "date", "uptime", "realpath", "readlink", "echo",
    "basename", "dirname", "tr", "sort", "uniq", "cut", "column", "jq",
    "git", "sqlite3", "ps", "lsof", "free", "vmstat", "iostat", "mount",
    "systemctl", "journalctl", "docker", "kubectl", "ffprobe",
    "nl", "od", "xxd", "strings",
})

# Binaries in the read-only set that are only read-only for *some* subcommands.
# Keyed on the subcommand rather than the whole tool, because the difference is
# real: `git status` is a read, `git push` is a write with a network effect.
_SUBCOMMAND_SCOPED: dict[str, frozenset[str]] = {
    "git": frozenset({
        "status", "log", "diff", "show", "blame", "describe", "rev-parse",
        "ls-files", "ls-tree", "ls-remote", "shortlog", "reflog", "whatchanged",
        "cat-file", "check-ignore", "check-attr", "grep", "count-objects",
        "verify-commit", "verify-tag", "merge-base", "name-rev", "show-ref",
        "var", "help", "annotate", "diff-tree", "for-each-ref", "symbolic-ref",
    }),
    "systemctl": frozenset({
        "status", "list-units", "list-unit-files", "list-timers", "show",
        "cat", "is-active", "is-enabled", "is-failed",
    }),
    "docker": frozenset({"ps", "images", "inspect", "logs", "version", "info"}),
    "kubectl": frozenset({
        "get", "describe", "logs", "explain", "version", "config", "api-resources",
    }),
    "pip": frozenset({"list", "show", "freeze", "check", "help"}),
    "npm": frozenset({"ls", "list", "view", "outdated", "help"}),
    "cargo": frozenset({"metadata", "tree", "search", "locate-project"}),
    "find": frozenset(),  # handled specially below
    "sed": frozenset(),  # handled specially below
    "xargs": frozenset(),  # never allowed, see _is_read_only
}

# Subcommand-scoped tools where the whole tool is refused, because any
# invocation of it is a write or an escalation path.
_REFUSED_ENTIRELY = frozenset({
    "xargs",  # turns a listing into execution
    "eval", "exec", "source", "sh", "bash", "zsh", "fish", "dash", "ksh",
    "ssh", "scp", "sftp", "rsync", "nc", "ncat", "netcat", "telnet",
    "curl", "wget", "ftp", "aria2c",
    "rm", "rmdir", "mv", "cp", "ln", "mkdir", "touch", "chmod", "chown",
    "dd", "mkfs", "mount", "umount", "kill", "killall", "pkill",
    "chgrp", "setfacl", "truncate", "shred", "mktemp", "install",
    "crontab", "at", "batch", "shutdown", "reboot", "halt", "poweroff",
    "useradd", "usermod", "passwd", "visudo", "iptables", "ufw", "sysctl",
    "modprobe", "insmod", "rmmod", "swapoff", "swapon", "parted", "fdisk",
    "apt", "apt-get", "yum", "dnf", "pacman", "brew", "snap", "flatpak",
    "pip3", "poetry", "uv", "conda", "gem", "composer",
    "chattr", "setcap", "insmod",
})

# `find` is read-only unless asked to act. `-delete`, `-exec` and `-execdir`
# all turn a search into a mutation or an arbitrary program.
_FIND_MUTATING = frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf"})
# `sed -i` rewrites in place; every other sed invocation is a read.
_SED_INPLACE = frozenset({"-i", "--in-place"})

# git's global options that consume the argument after them. Without this,
# `git -C /repo status` resolves to `/repo` instead of the `status` subcommand.
_GIT_VALUE_OPTIONS = frozenset({
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path",
})

# Hard rails. Applied even to an approved command.
_FORBIDDEN_SUBSTRINGS = ("\x00",)


@dataclass
class CommandResult:
    """What actually happened, in the shape the client and the model both want."""

    command: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool = False
    auto_approved: bool = False
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def as_text(self) -> str:
        """The single string handed back to the model as the tool result."""
        parts = []
        if self.stdout.strip():
            parts.append(self.stdout.rstrip())
        if self.stderr.strip():
            parts.append(f"[stderr]\n{self.stderr.rstrip()}")
        if self.timed_out:
            parts.append(f"[timed out after {self.duration_ms:.0f}ms]")
        if not parts:
            parts.append(f"[exit code {self.exit_code}, no output]")
        return "\n".join(parts)

    def as_payload(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "timed_out": self.timed_out,
            "auto_approved": self.auto_approved,
            "truncated": self.truncated,
            "ok": self.ok,
        }


@dataclass
class PendingRequest:
    """A command the model wants, waiting on the user's yes or no.

    ``event`` resolves to True (approved) or False (denied). A request that is
    never answered resolves to False on timeout, so a dropped connection can
    never turn into silent execution.
    """

    request_id: str
    conversation_id: str
    user_id: str
    command: str
    reason: str
    created_at: float
    event: asyncio.Event = field(default_factory=asyncio.Event)
    decision: bool | None = None

    @property
    def resolved(self) -> bool:
        return self.decision is not None

    def resolve(self, approved: bool) -> None:
        if not self.resolved:
            self.decision = approved
            self.event.set()


class CommandRegistry:
    """In-memory holding pen for commands awaiting approval.

    One instance per process. Requests are keyed by an unguessable id and carry
    the owning user, so a denial cannot be applied to somebody else's request
    even if the id leaks.
    """

    def __init__(self) -> None:
        self._requests: dict[str, PendingRequest] = {}

    def submit(self, request: PendingRequest) -> None:
        self._requests[request.request_id] = request

    def get(self, request_id: str, user_id: str) -> PendingRequest | None:
        request = self._requests.get(request_id)
        if request is None or request.user_id != user_id:
            return None
        return request

    def resolve(self, request_id: str, user_id: str, approved: bool) -> bool:
        request = self.get(request_id, user_id)
        if request is None or request.resolved:
            return False
        request.resolve(approved)
        logger.info(
            "command %s by user=%s",
            "approved" if approved else "denied",
            user_id,
        )
        return True

    def discard(self, request_id: str) -> None:
        self._requests.pop(request_id, None)

    def pending_for(self, conversation_id: str, user_id: str) -> list[dict[str, Any]]:
        return [
            {
                "request_id": request.request_id,
                "command": request.command,
                "reason": request.reason,
            }
            for request in self._requests.values()
            if request.conversation_id == conversation_id
            and request.user_id == user_id
            and not request.resolved
        ]

    async def wait(self, request: PendingRequest, timeout: float) -> bool:
        """Wait for a decision. Absence of one is a denial."""
        try:
            await asyncio.wait_for(request.event.wait(), timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError):
            request.resolve(False)
            logger.info("command request timed out and was denied: %s", request.command)
            return False
        finally:
            self.discard(request.request_id)
        return bool(request.decision)


REGISTRY = CommandRegistry()


def _mentions_sensitive_path(argv: list[str]) -> str | None:
    """The first argument that looks like a credential, if there is one.

    Reading a secret does not modify anything, but the stdout of a command is
    handed to the model. That makes ``cat .env`` an exfiltration path, so it is
    gated on the same terms as a write.
    """
    for argument in argv:
        for segment in re.split(r"[/\\=]", argument):
            if not segment:
                continue
            lowered = segment.lower()
            if lowered in _SENSITIVE_SEGMENTS:
                return argument
            if lowered.startswith(_SENSITIVE_PREFIXES):
                return argument
            if lowered.endswith(_SENSITIVE_SUFFIXES):
                return argument
    return None


def _subcommand_for(executable: str, rest: list[str]) -> str | None:
    """The effective subcommand, stepping over global options that take a value."""
    index = 0
    while index < len(rest):
        argument = rest[index]
        if argument in _GIT_VALUE_OPTIONS:
            index += 2
            continue
        if argument.startswith("-"):
            index += 1
            continue
        return argument
    return None


def _is_read_only(argv: list[str]) -> bool:
    """True only when this argv provably cannot change anything or leak a secret."""
    if not argv:
        return False
    executable = argv[0]
    if executable in _FORBIDDEN or executable in _REFUSED_ENTIRELY:
        return False
    if _mentions_sensitive_path(argv) is not None:
        return False

    rest = argv[1:]
    if executable == "find":
        # A search is a read; anything that makes it act is not.
        return not any(arg in _FIND_MUTATING for arg in rest)
    if executable == "sed":
        return not any(arg in _SED_INPLACE or arg.startswith("-i") for arg in rest)
    if executable in _SUBCOMMAND_SCOPED:
        allowed = _SUBCOMMAND_SCOPED[executable]
        if not allowed:
            return False
        subcommand = _subcommand_for(executable, rest)
        return subcommand is not None and subcommand in allowed

    return executable in _READ_ONLY


def _has_unescaped(text: str, pattern: re.Pattern[str]) -> bool:
    """True when the pattern appears outside quotes.

    Quoting makes a metacharacter literal, and that distinction decides real
    behaviour: ``find . -name '*.py'`` passes a literal asterisk to find, while
    ``ls *.py`` lets the shell expand it into an argv nobody inspected. Checking
    the raw string would reject both; checking quotes rejects only the real one.
    """
    quote: str | None = None
    index = 0
    while index < len(text):
        character = text[index]
        if character == "\\" and quote != "'":
            index += 2
            continue
        if quote is not None:
            if character == quote:
                quote = None
            index += 1
            continue
        if character in "\"'":
            quote = character
            index += 1
            continue
        if pattern.match(character):
            return True
        index += 1
    return False


def classify(command: str) -> tuple[bool, str]:
    """Decide whether a command may run unattended, and say why.

    Returns ``(auto_approved, reason)``. ``reason`` is written for the user, so
    it names the specific part that disqualified the command rather than just
    reporting a boolean.
    """
    stripped = command.strip()
    if not stripped:
        return False, "The command was empty."
    if any(bad in stripped for bad in _FORBIDDEN_SUBSTRINGS):
        return False, "The command contains a null byte."
    for forbidden in sorted(_FORBIDDEN):
        if re.search(rf"(^|[\s;|&(]){re.escape(forbidden)}($|[\s;|&)])", stripped):
            return False, f"`{forbidden}` needs privileges this tool does not have."

    # Substitution and redirection happen before any allowlist can apply, so
    # they disqualify the whole line rather than one segment.
    if _SUBSTITUTION.search(stripped):
        return False, "Command substitution can run anything, so it cannot be checked in advance."
    if _REDIRECT_OR_BACKGROUND.search(stripped):
        return False, "Redirection and backgrounding write outside the command itself."
    if re.search(r"[\n\r]", stripped):
        return False, "A command may not span multiple lines."
    if _HOME_OR_VARIABLE.search(stripped):
        return False, "`~` and `$` expand into paths and environment values the check never saw."
    if _has_unescaped(stripped, _GLOB_OR_EXPANSION):
        return False, "Globbing and brace expansion can add arguments the check never saw."

    segments = [part.strip() for part in _CHAIN_OPERATORS.split(stripped) if part.strip()]
    if not segments:
        return False, "The command was empty."

    for segment in segments:
        try:
            argv = shlex.split(segment)
        except ValueError:
            return False, f"Could not parse `{segment}` as a command."
        if not argv:
            continue
        if _is_read_only(argv):
            continue
        executable = argv[0]
        if executable in _FORBIDDEN or executable in _REFUSED_ENTIRELY:
            return False, f"`{executable}` changes the system or runs a nested shell."
        sensitive = _mentions_sensitive_path(argv)
        if sensitive is not None:
            return False, f"`{sensitive}` looks like a credential, and command output goes to the model."
        if executable in _SUBCOMMAND_SCOPED and _SUBCOMMAND_SCOPED[executable]:
            subcommand = _subcommand_for(executable, argv[1:]) or ""
            shown = f"{executable} {subcommand}".strip()
            return False, f"`{shown}` is not one of the read-only subcommands, so it needs your approval."
        return False, f"`{executable}` is not on the read-only list."

    return True, "Every part of this command is read-only."


async def run_command(
    command: str,
    *,
    conversation_id: str,
    user_id: str,
    reason: str = "",
    auto_approve: bool = True,
    request_id: str | None = None,
) -> CommandResult:
    """Run one command, asking the user first unless it is provably read-only.

    ``auto_approve=False`` forces the approval round-trip even for a read-only
    command, which is what the "always ask" path uses.
    """
    import time
    import uuid

    auto_approved, explanation = classify(command)
    should_auto_run = auto_approve and auto_approved

    if not should_auto_run:
        pending = PendingRequest(
            request_id=request_id or uuid.uuid4().hex,
            conversation_id=conversation_id,
            user_id=user_id,
            command=command,
            reason=reason or explanation,
            created_at=time.time(),
        )
        REGISTRY.submit(pending)
        logger.info("command awaiting approval: %s (%s)", command, explanation)
        approved = await REGISTRY.wait(pending, settings.command_approval_timeout_seconds)
        if not approved:
            return CommandResult(
                command=command,
                exit_code=None,
                stdout="",
                stderr="The user did not approve this command, so it did not run.",
                duration_ms=0.0,
                auto_approved=False,
            )
        should_auto_run = True

    return await _execute(command, auto_approved=should_auto_run)


async def _execute(command: str, *, auto_approved: bool) -> CommandResult:
    import time

    timeout = settings.command_timeout_seconds
    limit = settings.command_max_output_bytes
    started = time.perf_counter()
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=settings.command_working_directory or None,
        )
    except (OSError, ValueError) as exc:
        return CommandResult(
            command=command,
            exit_code=None,
            stdout="",
            stderr=f"Could not start the command: {exc}",
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            auto_approved=auto_approved,
        )

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        timed_out = False
    except (TimeoutError, asyncio.TimeoutError):
        # Kill the whole process group: a shell that spawned children would
        # otherwise leave them running after the timeout.
        _terminate(process)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
        except (TimeoutError, asyncio.TimeoutError):
            stdout, stderr = b"", b""
        timed_out = True

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    out, out_truncated = _decode_and_cap(stdout, limit)
    err, err_truncated = _decode_and_cap(stderr, limit)
    return CommandResult(
        command=command,
        exit_code=process.returncode,
        stdout=out,
        stderr=err if timed_out else err,
        duration_ms=duration_ms,
        timed_out=timed_out,
        auto_approved=auto_approved,
        truncated=out_truncated or err_truncated,
    )


def _terminate(process: Any) -> None:
    import signal

    try:
        os_killpg = getattr(process, "_transport", None)
        if os_killpg is not None:
            process.kill()
        else:  # pragma: no cover - platform fallback
            process.send_signal(signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass


def _decode_and_cap(raw: bytes, limit: int) -> tuple[str, bool]:
    text = (raw or b"").decode("utf-8", errors="replace")
    if len(text) <= limit:
        return text, False
    # Keep the tail: for a compiler or a test run, the failure is at the end.
    return text[-limit:] + f"\n[truncated to the last {limit} characters]", True


def run_shell_tool(command: str, reason: str = "") -> str:
    """Synchronous entry point, used only where no event loop is available."""
    return asyncio.run(
        run_command(
            command,
            conversation_id="sync",
            user_id="sync",
            reason=reason,
            auto_approve=False,
        )
    ).as_text()


SHELL_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "run_shell_command",
        "description": (
            "Run a single CLI command on the user's machine and return its "
            "output. Read-only commands (ls, cat, git status, pytest, ...) run "
            "immediately. Anything that writes, deletes, installs or reaches "
            "the network is held and shown to the user for approval first, and "
            "returns without running if they decline. Pass one command at a "
            "time; do not chain with && or ;. Prefer absolute or repo-relative "
            "paths, and never use sudo."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The exact command line to execute.",
                },
                "reason": {
                    "type": "string",
                    "description": "One short sentence on why this command is needed.",
                },
            },
            "required": ["command"],
        },
    },
}