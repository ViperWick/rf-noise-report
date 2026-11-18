import tempfile
import unittest
from shutil import copyfile
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

    def test_run_marks_padded_measurements_as_fail(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)

            run(
                root / "sample_data" / "raw",
                root / "sample_data" / "illustrative_limits.csv",
                out_dir,
            )

            summary = (out_dir / "summary.md").read_text(encoding="utf-8")
            self.assertIn("Loaded unit: **5 pass, 3 fail**.", summary)
            self.assertIn(
                "LTE B7 aux loaded is missing measurement(s) at channel(s)",
                summary,
            )
            self.assertIn("incomplete series cannot pass", summary)

    def test_missing_loaded_config_raises_readable_error(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp) / "raw"
            raw_dir.mkdir()
            copyfile(
                root / "sample_data" / "raw" / "LTE_B3_Baseline.csv",
                raw_dir / "LTE_B3_Baseline.csv",
            )

            with self.assertRaisesRegex(
                ValueError,
                "Band B3 is missing Loaded main measurements",
            ):
                run(
                    raw_dir,
                    root / "sample_data" / "illustrative_limits.csv",
                    Path(tmp) / "out",
                )


if __name__ == "__main__":
    unittest.main()
