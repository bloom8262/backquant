#!/usr/bin/env python3
"""Download normalized US daily bars from Yahoo Finance.

Examples:
    python /app/scripts/us_download.py QQQ VOO VIX
    python /app/scripts/us_download.py SPX=^GSPC

The left side of ``DB_SYMBOL=YAHOO_SYMBOL`` is used as the CSV filename and
database symbol. Common Yahoo index aliases (currently VIX) work without an
explicit mapping.
"""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd


DEFAULT_OUTPUT_DIR = Path(os.getenv("US_EQUITY_DATA_DIR", "/data/backtest/us_equity"))
DEFAULT_START = os.getenv("US_EQUITY_START_DATE", "1990-01-01")
DEFAULT_SYMBOLS = ("QQQ", "TQQQ", "VOO")
YAHOO_ALIASES = {"VIX": "^VIX"}
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9._-]{1,16}$")


@dataclass(frozen=True)
class SymbolSpec:
    db_symbol: str
    yahoo_symbol: str

    @property
    def filename(self) -> str:
        return f"{self.db_symbol}.csv"


def parse_symbol_spec(raw: str) -> SymbolSpec:
    value = str(raw or "").strip()
    if not value:
        raise ValueError("symbol cannot be empty")

    if "=" in value:
        db_raw, yahoo_raw = value.split("=", 1)
        db_symbol = db_raw.strip().upper()
        yahoo_symbol = yahoo_raw.strip().upper()
    else:
        yahoo_symbol = value.upper()
        db_symbol = yahoo_symbol.lstrip("^")
        yahoo_symbol = YAHOO_ALIASES.get(db_symbol, yahoo_symbol)

    if not SYMBOL_PATTERN.fullmatch(db_symbol):
        raise ValueError(
            f"invalid database symbol {db_symbol!r}; use 1-16 letters, numbers, '.', '_' or '-'"
        )
    if not yahoo_symbol or any(char.isspace() for char in yahoo_symbol):
        raise ValueError(f"invalid Yahoo symbol {yahoo_symbol!r}")
    return SymbolSpec(db_symbol=db_symbol, yahoo_symbol=yahoo_symbol)


def parse_symbol_specs(values: Iterable[str]) -> list[SymbolSpec]:
    specs: list[SymbolSpec] = []
    seen: set[str] = set()
    for raw in values:
        spec = parse_symbol_spec(raw)
        if spec.db_symbol in seen:
            continue
        specs.append(spec)
        seen.add(spec.db_symbol)
    return specs


def normalize_download_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["date", "close", "high", "low", "open", "volume"])

    normalized = frame.copy()
    if isinstance(normalized.columns, pd.MultiIndex):
        normalized.columns = [str(column[0]) for column in normalized.columns]

    normalized = normalized.reset_index()
    normalized.columns = [str(column).strip().lower() for column in normalized.columns]
    if "date" not in normalized.columns and "datetime" in normalized.columns:
        normalized = normalized.rename(columns={"datetime": "date"})

    required = ["date", "close", "high", "low", "open", "volume"]
    missing = [column for column in required if column not in normalized.columns]
    if missing:
        raise ValueError(f"downloaded data is missing columns: {', '.join(missing)}")

    result = normalized[required].copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for column in ("close", "high", "low", "open", "volume"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result["volume"] = result["volume"].fillna(0).clip(lower=0).round().astype("int64")
    result = result.dropna(subset=["date", "close", "high", "low", "open"])
    return result.drop_duplicates(subset=["date"], keep="last").sort_values("date")


def read_normalized_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["date", "close", "high", "low", "open", "volume"])
    frame = pd.read_csv(path)
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    required = ["date", "close", "high", "low", "open", "volume"]
    if any(column not in frame.columns for column in required):
        raise ValueError(f"existing CSV is not in normalized format: {path}")
    result = frame[required].copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for column in ("close", "high", "low", "open", "volume"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result["volume"] = result["volume"].fillna(0).clip(lower=0).round().astype("int64")
    return result.dropna(subset=["date", "close", "high", "low", "open"])


def download_symbol(
    spec: SymbolSpec,
    *,
    output_dir: Path,
    start: str,
    end: str,
    incremental: bool = True,
    overlap_days: int = 7,
    repair: bool = True,
) -> tuple[Path, int, str | None, str | None]:
    import yfinance as yf

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / spec.filename
    existing = read_normalized_csv(output_path) if incremental else pd.DataFrame()
    request_start = start
    if incremental and not existing.empty:
        last_date = pd.Timestamp(existing["date"].max())
        request_start = (last_date - pd.Timedelta(days=max(0, overlap_days))).strftime("%Y-%m-%d")

    downloaded = yf.download(
        spec.yahoo_symbol,
        start=request_start,
        end=end,
        interval="1d",
        auto_adjust=True,
        actions=False,
        repair=repair,
        progress=False,
        threads=False,
        multi_level_index=False,
    )
    fresh = normalize_download_frame(downloaded)
    if fresh.empty and existing.empty:
        raise RuntimeError(f"Yahoo returned no daily data for {spec.yahoo_symbol}")

    combined = pd.concat([existing, fresh], ignore_index=True) if not existing.empty else fresh
    combined = combined.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    combined.to_csv(output_path, index=False, lineterminator="\n")
    min_date = None if combined.empty else str(combined["date"].iloc[0])
    max_date = None if combined.empty else str(combined["date"].iloc[-1])
    return output_path, len(combined), min_date, max_date


def _default_end_date() -> str:
    # yfinance's end is exclusive, so tomorrow includes today's available bar.
    return (date.today() + timedelta(days=1)).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download normalized US daily bars from Yahoo Finance")
    parser.add_argument(
        "symbols",
        nargs="*",
        help="Symbols such as QQQ VOO VIX or DB_SYMBOL=YAHOO_SYMBOL (for example SPX=^GSPC)",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--start", default=DEFAULT_START, help="Start date for a new CSV (inclusive)")
    parser.add_argument("--end", default=_default_end_date(), help="End date (exclusive)")
    parser.add_argument("--full", action="store_true", help="Ignore an existing CSV and download from --start")
    parser.add_argument("--overlap-days", type=int, default=7, help="Redownload this many days when updating")
    parser.add_argument("--no-repair", action="store_true", help="Disable yfinance price repair")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raw_symbols = args.symbols or [
        item.strip()
        for item in os.getenv("US_EQUITY_SYMBOLS", ",".join(DEFAULT_SYMBOLS)).split(",")
        if item.strip()
    ]
    try:
        specs = parse_symbol_specs(raw_symbols)
        if not specs:
            raise ValueError("at least one symbol is required")
        for spec in specs:
            path, rows, min_date, max_date = download_symbol(
                spec,
                output_dir=args.output_dir,
                start=args.start,
                end=args.end,
                incremental=not args.full,
                overlap_days=args.overlap_days,
                repair=not args.no_repair,
            )
            print(
                f"downloaded {spec.db_symbol} ({spec.yahoo_symbol}): "
                f"{rows} rows, {min_date}..{max_date}, {path}"
            )
    except Exception as exc:
        print(f"error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
