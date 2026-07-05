import os
import csv
import zipfile
from decimal import Decimal
from datetime import datetime, timezone, timedelta

import pymysql


ZIP_DIR = "./download"

DB_ROOT_CONFIG = {
    "host": "backquant-mariadb-1",
    "port": 3306,
    "user": "root",
    "password": "backquant_root_pass",
    "charset": "utf8mb4",
    "autocommit": True,
}

DB_NAME = "crypto"
TABLE_NAME = "btc_usdt_15m"


CREATE_DATABASE_SQL = f"""
CREATE DATABASE IF NOT EXISTS {DB_NAME}
DEFAULT CHARACTER SET utf8mb4
DEFAULT COLLATE utf8mb4_general_ci;
"""


CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    open_time BIGINT NOT NULL,
    open_datetime DATETIME NOT NULL,
    open DECIMAL(30, 10) NOT NULL,
    high DECIMAL(30, 10) NOT NULL,
    low DECIMAL(30, 10) NOT NULL,
    close DECIMAL(30, 10) NOT NULL,
    volume DECIMAL(30, 10) NOT NULL,
    close_time BIGINT NOT NULL,
    close_datetime DATETIME NOT NULL,
    quote_volume DECIMAL(30, 10) NOT NULL,
    count BIGINT NOT NULL,
    taker_buy_volume DECIMAL(30, 10) NOT NULL,
    taker_buy_quote_volume DECIMAL(30, 10) NOT NULL,
    ignore_col DECIMAL(30, 10) NOT NULL DEFAULT 0,
    PRIMARY KEY (open_time),
    KEY idx_open_datetime (open_datetime),
    KEY idx_close_time (close_time),
    KEY idx_close_datetime (close_datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


INSERT_SQL = f"""
INSERT INTO {TABLE_NAME} (
    open_time,
    open_datetime,
    open,
    high,
    low,
    close,
    volume,
    close_time,
    close_datetime,
    quote_volume,
    count,
    taker_buy_volume,
    taker_buy_quote_volume,
    ignore_col
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    open_datetime = VALUES(open_datetime),
    open = VALUES(open),
    high = VALUES(high),
    low = VALUES(low),
    close = VALUES(close),
    volume = VALUES(volume),
    close_time = VALUES(close_time),
    close_datetime = VALUES(close_datetime),
    quote_volume = VALUES(quote_volume),
    count = VALUES(count),
    taker_buy_volume = VALUES(taker_buy_volume),
    taker_buy_quote_volume = VALUES(taker_buy_quote_volume),
    ignore_col = VALUES(ignore_col);
"""


def ms_to_datetime(ms):
    return (
        datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)
        .astimezone(timezone(timedelta(hours=8)))
        .replace(tzinfo=None)
    )


def parse_row(row):
    open_time = int(row[0])
    close_time = int(row[6])

    return (
        open_time,
        ms_to_datetime(open_time),
        Decimal(row[1]),
        Decimal(row[2]),
        Decimal(row[3]),
        Decimal(row[4]),
        Decimal(row[5]),
        close_time,
        ms_to_datetime(close_time),
        Decimal(row[7]),
        int(row[8]),
        Decimal(row[9]),
        Decimal(row[10]),
        Decimal(row[11]),
    )


def init_database():
    conn = pymysql.connect(**DB_ROOT_CONFIG)

    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_DATABASE_SQL)
            print("DATABASE READY:", DB_NAME)
    finally:
        conn.close()


def get_db_conn():
    config = DB_ROOT_CONFIG.copy()
    config["database"] = DB_NAME
    config["autocommit"] = False
    return pymysql.connect(**config)


def init_table(conn):
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)
    conn.commit()
    print("TABLE READY:", TABLE_NAME)


def import_zip_file(conn, zip_path, batch_size=5000):
    total = 0

    with zipfile.ZipFile(zip_path, "r") as z:
        csv_files = [name for name in z.namelist() if name.endswith(".csv")]

        if not csv_files:
            print("NO CSV:", zip_path)
            return 0

        csv_name = csv_files[0]

        with z.open(csv_name, "r") as f:
            text = (line.decode("utf-8").strip() for line in f)
            reader = csv.reader(text)

            batch = []

            for row in reader:
                if not row:
                    continue

                if row[0] == "open_time":
                    continue

                batch.append(parse_row(row))

                if len(batch) >= batch_size:
                    with conn.cursor() as cur:
                        cur.executemany(INSERT_SQL, batch)
                    conn.commit()

                    total += len(batch)
                    print("BATCH:", os.path.basename(zip_path), total)
                    batch.clear()

            if batch:
                with conn.cursor() as cur:
                    cur.executemany(INSERT_SQL, batch)
                conn.commit()

                total += len(batch)

    print("IMPORTED:", os.path.basename(zip_path), total)
    return total


def main():
    init_database()

    conn = get_db_conn()

    try:
        init_table(conn)

        zip_files = sorted(
            os.path.join(ZIP_DIR, name)
            for name in os.listdir(ZIP_DIR)
            if name.endswith(".zip")
        )

        print("ZIP COUNT:", len(zip_files))

        grand_total = 0

        for zip_path in zip_files:
            try:
                grand_total += import_zip_file(conn, zip_path)
            except Exception as e:
                conn.rollback()
                print("FAILED:", zip_path, e)

        print("DONE:", grand_total)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
