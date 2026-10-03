"""Guard against undefined global references in the application package.

Python resolves the class named in an ``except`` clause only when an exception
actually reaches it. A handler that catches a name the module never imported
therefore compiles, imports, and passes every happy-path test -- then raises
NameError at the exact moment the error path is exercised. That is how a stored
key that fails to decrypt ended up returning a bare "Internal Server Error"
instead of the intended message.

This walks every module in ``app/`` and resolves each global name it references.
"""

from __future__ import annotations

import ast
import builtins
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"


def _module_files() -> list[Path]:
    return sorted(APP_DIR.rglob("*.py"))


def _bound_names(tree: ast.AST) -> set[str]:
    """Names a module legitimately binds at module scope."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.Global):
            names.update(node.names)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            names.add(node.rest)
    return names


def _referenced_globals(tree: ast.AST) -> set[str]:
    """Names read as globals, excluding attributes, locals and comprehensions."""
    bound_locally: set[str] = set()
    referenced: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            for arg in _all_args(node):
                bound_locally.add(arg)
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
                    bound_locally.add(child.id)
                elif isinstance(child, (ast.Import, ast.ImportFrom)):
                    for alias in child.names:
                        bound_locally.add(alias.asname or alias.name.split(".")[0])
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            referenced.add(node.id)
    return referenced - bound_locally


def _all_args(node) -> set[str]:
    args = node.args
    collected = {arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
    if args.vararg:
        collected.add(args.vararg.arg)
    if args.kwarg:
        collected.add(args.kwarg.arg)
    return collected


@pytest.mark.parametrize(
    "module_path",
    _module_files(),
    ids=lambda path: path.relative_to(APP_DIR).as_posix(),
)
def test_module_references_no_undefined_globals(module_path: Path):
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module_path))

    # Conditional and platform-specific imports (e.g. inside a try/except
    # ImportError) are legitimately optional, so fall back to whatever the
    # module actually binds at runtime.
    import importlib

    module_name = "app." + ".".join(module_path.relative_to(APP_DIR).with_suffix("").parts)
    module_name = module_name.removesuffix(".__init__")
    module = importlib.import_module(module_name)
    runtime_globals = set(vars(module))

    allowed = _bound_names(tree) | set(dir(builtins)) | runtime_globals
    missing = sorted(_referenced_globals(tree) - allowed)

    assert not missing, (
        f"{module_path.relative_to(APP_DIR)} references names that are never "
        f"imported or defined: {', '.join(missing)}"
    )