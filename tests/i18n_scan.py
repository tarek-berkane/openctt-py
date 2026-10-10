"""Finds every translatable string in octt/ (calls to tr(...) and N_(...)) and compares with the catalogs.
Run `python -m tests.i18n_scan` (or `make i18n`) to list what is missing / unused per language."""
import ast
import re
import sys
from pathlib import Path

from octt import i18n

ROOT = Path(__file__).resolve().parent.parent / "octt"
HOLE = re.compile(r"\{(\w+)[^}]*\}")


def _strings(node):
    """Literal strings a call argument can evaluate to: 'x', or 'a' if c else 'b'."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        return _strings(node.body) + _strings(node.orelse)
    return []


def collect_keys() -> dict[str, list[str]]:
    keys: dict[str, list[str]] = {}
    dynamic = []
    for path in sorted(ROOT.rglob("*.py")):
        if "locales" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("tr", "N_"):
                where = f"{path.relative_to(ROOT.parent)}:{node.lineno}"
                found = _strings(node.args[0]) if node.args else []
                if not found:
                    dynamic.append(where)
                for s in found:
                    keys.setdefault(s, []).append(where)
    keys["__dynamic__"] = dynamic  # tr(variable): fine only if the variable holds an N_ literal elsewhere
    return keys


def holes(msg: str) -> set[str]:
    return set(HOLE.findall(msg))


def problems() -> dict[str, list[str]]:
    keys = collect_keys()
    keys.pop("__dynamic__")
    out = {}
    for code in i18n.LANGUAGES:
        if code == "en":
            continue
        cat = i18n.catalog(code)
        miss = [k for k in keys if k not in cat]
        unused = [k for k in cat if k not in keys]
        bad = [k for k in keys if k in cat and holes(k) != holes(cat[k])]
        out[code] = [f"MISSING  {k!r}  ({keys[k][0]})" for k in miss] + [f"UNUSED   {k!r}" for k in unused] + \
                    [f"PLACEHOLDERS differ  {k!r} -> {cat[k]!r}" for k in bad]
    return out


if __name__ == "__main__":
    bad = problems()
    for code, lines in bad.items():
        print(f"== {code}: {len(lines)} problem(s)")
        print("\n".join(lines))
    sys.exit(any(bad.values()))
