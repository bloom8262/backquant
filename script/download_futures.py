import os
import re
import time
import requests
import xml.etree.ElementTree as ET
from urllib.parse import quote

BASE_DOWNLOAD = "https://data.binance.vision"
BASE_LIST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"

#PREFIX = "data/futures/cm/monthly/klines/BTCUSD_PERP/15m/"
PREFIX = "data/futures/um/monthly/klines/BTCUSDT/15m/"
#OUT_DIR = "./binance_cm_btcusd_perp_15m"
OUT_DIR = "./binance_um_btcusdt_15m"
START_MONTH = 202008

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0"})


def list_s3(prefix):
    all_keys = []
    token = None

    while True:
        url = f"{BASE_LIST}?list-type=2&prefix={quote(prefix)}"
        if token:
            url += f"&continuation-token={quote(token)}"

        print("LIST:", url)

        r = session.get(url, timeout=30)
        print("STATUS:", r.status_code, "LEN:", len(r.text))
        r.raise_for_status()

        if "<ListBucketResult" not in r.text:
            print("RESPONSE HEAD:")
            print(r.text[:800])
            raise RuntimeError("返回内容不是 S3 XML 列表")

        root = ET.fromstring(r.text)
        ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}

        keys = [
            x.text for x in root.findall("s3:Contents/s3:Key", ns)
            if x.text
        ]

        all_keys.extend(keys)

        is_truncated = root.findtext("s3:IsTruncated", default="false", namespaces=ns)
        token = root.findtext("s3:NextContinuationToken", default=None, namespaces=ns)

        if is_truncated != "true" or not token:
            break

    return sorted(set(all_keys))


def extract_month(filename):
    """
    例如:
    BTCUSD_PERP-15m-2020-08.zip -> 202008
    """
    m = re.search(r"-(\d{4})-(\d{2})\.zip$", filename)
    if not m:
        return None

    return int(m.group(1) + m.group(2))


def download_file(key):
    filename = key.split("/")[-1]

    url = f"{BASE_DOWNLOAD}/{key}"
    path = os.path.join(OUT_DIR, filename)

    os.makedirs(OUT_DIR, exist_ok=True)

    if os.path.exists(path) and os.path.getsize(path) > 0:
        print("SKIP:", path)
        return

    print("DOWN:", url)

    tmp = path + ".part"

    try:
        with session.get(url, stream=True, timeout=60) as r:
            print("DOWN STATUS:", r.status_code)
            r.raise_for_status()

            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1024 * 1024):
                    if chunk:
                        f.write(chunk)

        os.replace(tmp, path)
        print("OK:", path)

    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def main():
    keys = list_s3(PREFIX)

    zip_keys = []

    for key in keys:
        filename = key.split("/")[-1]

        if not filename.endswith(".zip"):
            continue

        if filename.endswith(".CHECKSUM"):
            continue

        month = extract_month(filename)
        if month is None:
            continue

        if month < START_MONTH:
            continue

        zip_keys.append(key)

    print("matched zip files:", len(zip_keys))

    for key in zip_keys:
        download_file(key)
        time.sleep(0.2)

    print("DONE, downloaded/skipped:", len(zip_keys))


if __name__ == "__main__":
    main()
