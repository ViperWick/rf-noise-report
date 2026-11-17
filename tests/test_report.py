import tempfile
import unittest
from pathlib import Path

from report import run


class ReportOutputTests(unittest.TestCase):
    def test_run_preserves_existing_chart_pngs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            sentinel = out_dir / "charts" / "customer_chart.png"
            sentinel.parent.mkdir(parents=True)
            sentinel.write_text("do not delete", encoding="utf-8")

            run(
                root / "sample_data" / "raw",
                root / "sample_data" / "illustrative_limits.csv",
                out_dir,
            )

            self.assertTrue(sentinel.exists())
            self.assertTrue((out_dir / "summary.md").exists())
            self.assertTrue((out_dir / "charts" / "overview.png").exists())


if __name__ == "__main__":
    unittest.main()
