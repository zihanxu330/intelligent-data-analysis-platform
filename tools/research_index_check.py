# -*- coding: utf-8 -*-
"""只读检查 docs/research-index.md 与 docs/research-corrections.md 的一致性。"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX = Path("docs/research-index.md")
CORRECTIONS = Path("docs/research-corrections.md")
ALLOWED_REVIEW = {"人工复核（结论层）", "报告缺失", "自动摘要", "未核实"}


def _rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        if not line.startswith("| `research_stage"):
            continue
        parts = [p.strip() for p in line.split("|")[1:-1]]
        if len(parts) >= 8:
            rows.append(parts)
    return rows


def run(root: Path | None = None) -> dict[str, Any]:
    root = (root or PROJECT_ROOT).resolve()
    issues: list[dict[str, str]] = []
    index = root / INDEX
    corrections = root / CORRECTIONS
    rows: list[list[str]] = []
    if not index.exists():
        issues.append({"severity": "blocked", "item": str(INDEX), "detail": "index missing"})
    else:
        rows = _rows(index.read_text(encoding="utf-8"))
        seen = set()
        for r in rows:
            d = r[0].strip("`")
            if d in seen:
                issues.append({"severity": "error", "item": d, "detail": "duplicate stage directory"})
            seen.add(d)
            rel = Path("output") / d
            if not (root / rel).is_dir():
                issues.append({"severity": "error", "item": d, "detail": "directory missing"})
            report = (root / rel / "final_assessment.md")
            readme = (root / rel / "README.md")
            has = report.exists() or readme.exists()
            review = r[4] if len(r) > 4 else ""
            if review not in ALLOWED_REVIEW:
                issues.append({"severity": "warning", "item": d, "detail": f"unknown review status {review!r}"})
            if not has and review != "报告缺失":
                issues.append({"severity": "warning", "item": d, "detail": "report missing but not marked 报告缺失"})
    if not corrections.exists():
        issues.append({"severity": "warning", "item": str(CORRECTIONS), "detail": "corrections file missing"})
        paths = []
    else:
        text = corrections.read_text(encoding="utf-8")
        paths = re.findall(r"output/research_stage[0-9A-Za-z_./-]+", text)
        for p in sorted(set(paths)):
            if not (root / p).exists():
                issues.append({"severity": "error", "item": p, "detail": "correction source path missing"})
    return {
        "root": str(root),
        "status": "ok" if not any(i["severity"] in ("error", "blocked") for i in issues) else "error",
        "index_rows": len(rows),
        "review_manual": sum(1 for r in rows if len(r) > 4 and r[4] == "人工复核（结论层）"),
        "review_missing": sum(1 for r in rows if len(r) > 4 and r[4] == "报告缺失"),
        "review_auto": sum(1 for r in rows if len(r) > 4 and r[4] == "自动摘要"),
        "correction_paths": len(set(paths)),
        "issues": issues,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only research index consistency check")
    ap.add_argument("--root", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    report = run(Path(a.root) if a.root else None)
    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"status: {report['status']}")
        print(f"rows: {report['index_rows']} manual={report['review_manual']} missing={report['review_missing']}")
        for i in report["issues"]:
            print(f"[{i['severity']}] {i['item']}: {i['detail']}")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
