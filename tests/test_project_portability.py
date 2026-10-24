"""Guard the supported application entrypoints against machine-specific paths."""
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
MACHINE_ROOT = r"C:\Users\22646\Desktop\项目\quant_ai_updated\quant"
MACHINE_PYTHON = r"C:\Users\22646\AppData\Local\Programs\Python\Python311\python.exe"


class ProjectPortabilityTests(unittest.TestCase):
    def test_supported_entrypoints_have_no_machine_specific_paths(self):
        files = [
            ROOT / "pipeline.py",
            ROOT / "paper_trade.py",
            ROOT / "data_engine" / "raw_market.py",
            ROOT / "backtest" / "portfolio.py",
            ROOT / "models" / "predict.py",
        ]
        for path in files:
            with self.subTest(path=path.relative_to(ROOT)):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn(MACHINE_ROOT, text)
                self.assertNotIn(MACHINE_PYTHON, text)

    def test_missing_paper_filter_is_rejected_before_io(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "paper_trade.py"), "--symbols-file", "not-a-symbol-list.txt"],
            cwd=ROOT.parent, capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("does not define is_st_or_delisted", result.stderr)
        self.assertNotIn("FileNotFoundError", result.stderr)

    def test_unavailable_warning_model_is_rejected_before_io(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "paper_trade.py"), "--warn-model", "not-a-model.joblib"],
            cwd=ROOT.parent, capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--warn-model is unavailable", result.stderr)

    def test_paper_trade_help_starts_from_outside_project_root(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "paper_trade.py"), "--help"],
            cwd=ROOT.parent,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--industry-cap", result.stdout)


if __name__ == "__main__":
    unittest.main()
