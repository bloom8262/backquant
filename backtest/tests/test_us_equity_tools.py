from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


BACKTEST_ROOT = Path(__file__).resolve().parents[1]
if str(BACKTEST_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKTEST_ROOT))

from scripts.us_download import (  # noqa: E402
    normalize_download_frame,
    parse_symbol_spec,
    parse_symbol_specs,
)


def _load_import_module():
    module_path = BACKTEST_ROOT / "import_us_equity_to_mariadb.py"
    spec = importlib.util.spec_from_file_location("import_us_equity_to_mariadb", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


import_module = _load_import_module()


class UsEquityDownloadTests(unittest.TestCase):
    def test_vix_alias(self):
        spec = parse_symbol_spec("vix")
        self.assertEqual(spec.db_symbol, "VIX")
        self.assertEqual(spec.yahoo_symbol, "^VIX")

    def test_explicit_yahoo_mapping_and_deduplication(self):
        specs = parse_symbol_specs(["SPX=^GSPC", "spx=^gspc", "VOO"])
        self.assertEqual(
            [(item.db_symbol, item.yahoo_symbol) for item in specs],
            [("SPX", "^GSPC"), ("VOO", "VOO")],
        )

    def test_normalizes_yfinance_multi_index(self):
        index = pd.to_datetime(["2026-07-17", "2026-07-18"])
        columns = pd.MultiIndex.from_tuples(
            [(name, "VOO") for name in ("Close", "High", "Low", "Open", "Volume")]
        )
        frame = pd.DataFrame(
            [[600.0, 601.0, 598.0, 599.0, 100], [602.0, 603.0, 600.0, 601.0, None]],
            index=index,
            columns=columns,
        )
        frame.index.name = "Date"

        result = normalize_download_frame(frame)

        self.assertEqual(result.columns.tolist(), ["date", "close", "high", "low", "open", "volume"])
        self.assertEqual(result["date"].tolist(), ["2026-07-17", "2026-07-18"])
        self.assertEqual(result["volume"].tolist(), [100, 0])


class UsEquityImportTests(unittest.TestCase):
    def test_read_bar_csv_validates_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "VOO.csv"
            pd.DataFrame(
                [
                    ["2026-07-17", 600, 601, 598, 599, 100],
                    ["2026-07-17", 602, 603, 600, 601, 101],
                ],
                columns=["date", "close", "high", "low", "open", "volume"],
            ).to_csv(path, index=False)

            result = import_module.read_bar_csv(path)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["close"], 602)

    def test_rejects_unsafe_sql_identifier(self):
        with self.assertRaises(ValueError):
            import_module.quote_identifier("table; DROP DATABASE x")


if __name__ == "__main__":
    unittest.main()
