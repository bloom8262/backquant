#!/usr/bin/env python3
"""Download and/or import US daily bars into MariaDB."""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd

from scripts.us_download import DEFAULT_START, DEFAULT_SYMBOLS, download_symbol, parse_symbol_specs


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")
DEFAULT_DATA_DIR = Path(os.getenv("US_EQUITY_DATA_DIR", "/data/backtest/us_equity"))


@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    port: int
    user: str
    password: str
    database: str
    table: str

    @classmethod
    def from_env(cls) -> "DatabaseSettings":
        return cls(
            host=os.getenv("US_EQUITY_DB_HOST", os.getenv("DB_HOST", "mariadb")),
            port=int(os.getenv("US_EQUITY_DB_PORT", os.getenv("DB_PORT", "3306"))),
            user=os.getenv("US_EQUITY_DB_USER", "root"),
            password=os.getenv("US_EQUITY_DB_PASSWORD", os.getenv("MYSQL_ROOT_PASSWORD", "")),
            database=os.getenv("US_EQUITY_DB_NAME", "us_equity"),
            table=os.getenv("US_EQUITY_DB_TABLE", "tb_us_equity_1d"),
        )


def quote_identifier(value: str) -> str:
    if not IDENTIFIER_PATTERN.fullmatch(value or ""):
        raise ValueError(f"invalid SQL identifier: {value!r}")
    return f"`{value}`"


def connect_server(settings: DatabaseSettings):
    import pymysql

    return pymysql.connect(
        host=settings.host, port=settings.port, user=settings.user, password=settings.password,
        charset="utf8mb4", autocommit=False,
    )


def connect_database(settings: DatabaseSettings):
    import pymysql

    return pymysql.connect(
        host=settings.host, port=settings.port, user=settings.user, password=settings.password,
        database=settings.database, charset="utf8mb4", autocommit=False,
    )


def ensure_database(settings: DatabaseSettings) -> None:
    database = quote_identifier(settings.database)
    conn = connect_server(settings)
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {database} CHARACTER SET utf8mb4")
        conn.commit()
    finally:
        conn.close()


def ensure_table(conn, settings: DatabaseSettings) -> None:
    table = quote_identifier(settings.table)
    sql = f"""
    CREATE TABLE IF NOT EXISTS {table} (
        `symbol` VARCHAR(16) NOT NULL,
        `date` VARCHAR(10) NOT NULL,
        `close` DECIMAL(20, 10) NOT NULL,
        `high` DECIMAL(20, 10) NOT NULL,
        `low` DECIMAL(20, 10) NOT NULL,
        `open` DECIMAL(20, 10) NOT NULL,
        `volume` BIGINT UNSIGNED NOT NULL DEFAULT 0,
        PRIMARY KEY (`symbol`, `date`),
        KEY `idx_us_equity_date` (`date`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """
    with conn.cursor() as cursor:
        cursor.execute(sql)
    conn.commit()


def read_bar_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"CSV file not found: {path}")
    frame = pd.read_csv(path)
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    if "date" not in frame.columns and "datetime" in frame.columns:
        frame = frame.rename(columns={"datetime": "date"})
    required = ["date", "close", "high", "low", "open", "volume"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"{path} is missing columns: {', '.join(missing)}")

    result = frame[required].copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for column in ("close", "high", "low", "open", "volume"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result["volume"] = result["volume"].fillna(0).clip(lower=0).round().astype("int64")
    result = result.dropna(subset=["date", "close", "high", "low", "open"])
    result = result.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    if result.empty:
        raise ValueError(f"{path} contains no valid daily bars")
    return result


def _chunks(values: list[tuple], size: int) -> Iterable[list[tuple]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def import_frame(
    conn, settings: DatabaseSettings, symbol: str, frame: pd.DataFrame, *,
    batch_size: int = 1000, update_existing: bool = True,
) -> tuple[int, int]:
    table = quote_identifier(settings.table)
    duplicate_clause = """
        ON DUPLICATE KEY UPDATE
            `close` = VALUES(`close`), `high` = VALUES(`high`),
            `low` = VALUES(`low`), `open` = VALUES(`open`),
            `volume` = VALUES(`volume`)
    """ if update_existing else ""
    prefix = "INSERT" if update_existing else "INSERT IGNORE"
    sql = f"""
        {prefix} INTO {table} (`symbol`, `date`, `close`, `high`, `low`, `open`, `volume`)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        {duplicate_clause}
    """
    rows = [
        (symbol, row.date, float(row.close), float(row.high), float(row.low), float(row.open), int(row.volume))
        for row in frame.itertuples(index=False)
    ]
    affected = 0
    with conn.cursor() as cursor:
        for batch in _chunks(rows, max(1, batch_size)):
            affected += max(0, cursor.executemany(sql, batch) or 0)
    return len(rows), affected


def print_inventory(conn, settings: DatabaseSettings) -> None:
    table = quote_identifier(settings.table)
    with conn.cursor() as cursor:
        cursor.execute(
            f"SELECT `symbol`, COUNT(*), MIN(`date`), MAX(`date`) FROM {table} "
            "GROUP BY `symbol` ORDER BY `symbol`"
        )
        rows = cursor.fetchall()
    print("database inventory:" if rows else "database inventory: empty")
    for symbol, count, min_date, max_date in rows:
        print(f"  {symbol}: {count} rows, {min_date}..{max_date}")


def _default_end_date() -> str:
    return (date.today() + timedelta(days=1)).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import US daily bars into MariaDB")
    parser.add_argument(
        "symbols", nargs="*",
        help="Symbols such as QQQ VOO VIX or DB_SYMBOL=YAHOO_SYMBOL (for example SPX=^GSPC)",
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--download", action="store_true", help="Download/update CSV files before importing")
    parser.add_argument("--download-only", action="store_true", help="Download CSV files without touching MariaDB")
    parser.add_argument("--start", default=DEFAULT_START, help="Start date for a new CSV")
    parser.add_argument("--end", default=_default_end_date(), help="Yahoo end date (exclusive)")
    parser.add_argument("--full-download", action="store_true", help="Ignore existing CSV content")
    parser.add_argument("--overlap-days", type=int, default=7)
    parser.add_argument("--no-repair", action="store_true")
    parser.add_argument("--insert-ignore", action="store_true", help="Do not update existing symbol/date rows")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--inventory", action="store_true", help="Only show symbols currently in MariaDB")
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
        if args.download or args.download_only:
            for spec in specs:
                path, rows, min_date, max_date = download_symbol(
                    spec, output_dir=args.data_dir, start=args.start, end=args.end,
                    incremental=not args.full_download, overlap_days=args.overlap_days,
                    repair=not args.no_repair,
                )
                print(
                    f"downloaded {spec.db_symbol} ({spec.yahoo_symbol}): "
                    f"{rows} rows, {min_date}..{max_date}, {path}"
                )
        if args.download_only:
            return 0

        settings = DatabaseSettings.from_env()
        ensure_database(settings)
        conn = connect_database(settings)
        try:
            ensure_table(conn, settings)
            if args.inventory:
                print_inventory(conn, settings)
                return 0
            for spec in specs:
                frame = read_bar_csv(args.data_dir / spec.filename)
                source_rows, affected = import_frame(
                    conn, settings, spec.db_symbol, frame, batch_size=args.batch_size,
                    update_existing=not args.insert_ignore,
                )
                conn.commit()
                print(f"imported {spec.db_symbol}: {source_rows} source rows, {affected} affected rows")
            print_inventory(conn, settings)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
