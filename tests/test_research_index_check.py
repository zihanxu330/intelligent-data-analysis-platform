# -*- coding: utf-8 -*-
"""Offline tests for tools/research_index_check.py."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tools.research_index_check import main, run


def make(root: Path, rows=None, corrections=True, report=True):
    (root / "docs").mkdir(parents=True)
    (root / "output/research_stageA_20261021").mkdir(parents=True)
    if report:
        (root / "output/research_stageA_20261021/final_assessment.md").write_text("# report\n", encoding="utf-8")
    rows = rows or [
        "| `research_stageA_20261021` | final_assessment.md | c | 完成 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |",
    ]
    (root / "docs/research-index.md").write_text(
        "# idx\n\n| Stage 目录 | 主要产物 | 结论摘要 | 状态 | 复核 | 生产代码 | 生产DB | 模型 |\n"
        "|---|---|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n", encoding="utf-8")
    if corrections:
        (root / "docs/research-corrections.md").write_text(
            "`output/research_stageA_20261021/final_assessment.md`\n", encoding="utf-8")


class IndexCheckerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid(self):
        make(self.root)
        r = run(self.root)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["index_rows"], 1)
        self.assertEqual(r["review_manual"], 1)

    def test_missing_dir(self):
        make(self.root)
        import shutil
        shutil.rmtree(self.root / "output/research_stageA_20261021")
        r = run(self.root)
        self.assertEqual(r["status"], "error")

    def test_duplicate(self):
        row = "| `research_stageA_20261021` | final_assessment.md | c | 完成 | 人工复核（结论层） | 未核实 | 未核实 | 未核实 |"
        make(self.root, rows=[row, row])
        r = run(self.root)
        self.assertTrue(any(i["detail"] == "duplicate stage directory" for i in r["issues"]))

    def test_unknown_review(self):
        row = "| `research_stageA_20261021` | final_assessment.md | c | 完成 | mystery | 未核实 | 未核实 | 未核实 |"
        make(self.root, rows=[row])
        r = run(self.root)
        self.assertTrue(any(i["detail"].startswith("unknown review") for i in r["issues"]))

    def test_missing_correction_path(self):
        make(self.root, corrections=False)
        (self.root / "docs/research-corrections.md").write_text("`output/research_stageX_20261021/final_assessment.md`\n", encoding="utf-8")
        r = run(self.root)
        self.assertTrue(any(i["detail"] == "correction source path missing" for i in r["issues"]))

    def test_json_cli(self):
        make(self.root)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--root", str(self.root), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["status"], "ok")


if __name__ == "__main__":
    unittest.main()
