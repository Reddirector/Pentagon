# CLAUDE.md - Engineering Standards & Agent Conventions

This document defines the working conventions, toolchains, and quality levels for agents operating on the Pentagon codebase.

## Quality Levels

### LEVEL 1 (quick)
- **Use case**: Small fixes, scripts, quick answers.
- **Skills**: `implement`, `diagnosing-bugs`
- **Rule**: Make the change, run it once, summarize in 3 lines.

### LEVEL 2 (standard) - DEFAULT
- **Use case**: Standard feature work, bug fixes, refactorings.
- **Skills**: `grill-with-docs` (clarify requirements first), `to-spec`, `implement-spec`, `tdd`, `code-review`.
- **UI Work**: Always apply `frontend-design` for visual polish and accessibility.
- **Rule**: Plan, build, test, and self-review before handoff.

### LEVEL 3 (production)
- **Use case**: Major features, architectural overhauls, production ship-ready code.
- **Skills**: `grill-me`, `domain-modeling`, `to-spec`, `to-tickets`, `codebase-design`, `tdd`, `implement`, `review-team`, `improve-codebase-architecture`, `pr`.
- **UI Work**: Apply `frontend-design`.
- **Rule**: Show spec and tickets before coding. Complete with a self-review and retro via `retro`.

---

## Claude-Style Structured Output Standards

When generating responses, reports, analyses, or code reviews:
1. **Direct Answer First**: Open immediately with the core conclusion or solution. Zero conversational filler (`"Sure!", "Certainly!", "I can help with that."`).
2. **Grounding & Evidence**: Every claim must be grounded in facts or verified code. If an assumption is made, state it explicitly.
3. **Information Density & Hierarchy**:
   - Use bold lead-ins for scannable bullet points (`- **Component**: Details...`).
   - Use Markdown pipe tables for comparative parameters, metrics, or trade-offs.
   - Use GitHub-style callouts (`> [!NOTE]`, `> [!TIP]`, `> [!IMPORTANT]`, `> [!WARNING]`).
4. **Code Precision**:
   - Provide clickable file links using Markdown `file:///` paths.
   - Run type checks (`npm run check` or `pytest`) before presenting solutions.

---

## Agent Skills Configuration

- **Issue Tracker**: GitHub Issues (`gh`) with `.scratch/` fallback (configured in [`docs/agents/issue-tracker.md`](file:///home/aditya/Desktop/Pentagon/docs/agents/issue-tracker.md)).
- **Triage Vocabulary**: Canonical labels configured in [`docs/agents/triage-labels.md`](file:///home/aditya/Desktop/Pentagon/docs/agents/triage-labels.md).
- **Domain Docs**: Documented in [`docs/agents/domain.md`](file:///home/aditya/Desktop/Pentagon/docs/agents/domain.md).
- **Installed Skills**: Accessible in `~/.gemini/antigravity/skills`.
