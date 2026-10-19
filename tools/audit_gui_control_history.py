"""Inventory reachable Qt control rules with AST and commit provenance.

An inventory is evidence for the audit, never a substitute for widget tests.
"""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "Raporty/gui_recovery_20261018"
SETTERS = {"setEnabled", "setDisabled", "setTabEnabled", "setReadOnly", "setVisible", "blockSignals"}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def rules(source):
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr not in SETTERS:
            continue
        contexts = []; owner = "module"; cursor = node
        while cursor in parents:
            cursor = parents[cursor]
            if isinstance(cursor, (ast.If, ast.While)):
                contexts.append(ast.unparse(cursor.test))
            if isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef)):
                owner = cursor.name
                break
        found.append(dict(method=owner, line=node.lineno, call=ast.unparse(node), guards=contexts))
    return found


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    log = git("log", "--all", "--raw", "--no-abbrev", "--format=COMMIT %H %aI %s", "--", "src/gui/qt").decode("utf-8", "replace")
    (OUT / "git_gui_history.txt").write_text(log, encoding="utf-8")
    versions = {}; commit = ""
    for line in log.splitlines():
        if line.startswith("COMMIT "):
            commit = line[7:]
        elif line.startswith(":") and "\t" in line:
            meta, path = line.split("\t", 1)
            sha = meta.split()[3]
            if path.endswith(".py") and set(sha) != {"0"}:
                versions.setdefault(sha, dict(path=path, commit=commit))
    batch = subprocess.run(
        ["git", "cat-file", "--batch"], cwd=ROOT, input="".join(s+"\n" for s in versions).encode(), capture_output=True, check=True).stdout
    offset = 0; historical = []
    for sha, provenance in versions.items():
        end = batch.index(b"\n", offset); header = batch[offset:end].split(); size = int(header[2]); offset = end + 1
        source = batch[offset:offset+size].decode("utf-8", "replace"); offset += size + 1
        for rule in rules(source):
            historical.append(dict(**provenance, blob=sha, **rule))
    current = []
    for path in (ROOT / "src/gui/qt").rglob("*.py"):
        for rule in rules(path.read_text(encoding="utf-8-sig")):
            current.append(dict(path=path.relative_to(ROOT).as_posix(), **rule))
    reports = []
    pattern = re.compile(r"GUI|ustawieni|licenc|license|blokad|odblok|kolejk|lifecycle|kontrol|capabil", re.I)
    for path in (ROOT / "Raporty").rglob("*.md"):
        if OUT in path.parents: continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if pattern.search(text):
            excerpts = [dict(line=i, text=line) for i, line in enumerate(text.splitlines(), 1) if pattern.search(line)]
            reports.append(dict(path=path.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest(), excerpts=excerpts))
    result = dict(refs=git("show-ref").decode(), reachable_commits=int(git("rev-list", "--all", "--count")),
                  historical_gui_blobs=len(versions), historical_rules=historical, current_rules=current, reports=reports)
    (OUT / "control_history_inventory.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: len(v) if isinstance(v,list) else v for k,v in result.items() if k != "refs" and k not in ("historical_rules","current_rules","reports")}))
    print(f"rules: historical={len(historical)} current={len(current)} reports_read={len(reports)}")


if __name__ == "__main__":
    main()
