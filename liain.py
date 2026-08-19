import re
import zipfile
import csv
import io
import os
import sys
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from pyproj import Transformer
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk, BulkIndexError
from dotenv import load_dotenv

load_dotenv()

URL = "https://operateurs.liain.fr/ipe/"
ES_HOST    = os.environ["ES_HOST"]
ES_API_KEY = os.environ.get("ES_API_KEY")
ES_USER    = os.environ.get("ES_USERNAME")
ES_PASS    = os.environ.get("ES_PASSWORD")
ES_INDEX   = os.environ.get("ES_INDEX", "liain")

EXPECTED_FIELDS = 65  # CSV columns before we add the two localisation_ fields
                       # 63 original + Code_RNB + Date_RNB (added 2025)
BULK_CHUNK      = 500
CSV_ENCODING    = "utf-8-sig"  # handles UTF-8 BOM; fall back to latin-1 below if needed


def build_es_client() -> Elasticsearch:
    kwargs = {"hosts": [ES_HOST]}
    if ES_API_KEY:
        kwargs["api_key"] = ES_API_KEY
    elif ES_USER and ES_PASS:
        kwargs["basic_auth"] = (ES_USER, ES_PASS)
    else:
        print("WARNING: no credentials found in .env – connecting unauthenticated", file=sys.stderr)
    return Elasticsearch(**kwargs)


def find_archive_filename() -> str:
    """Scrape the IPE listing page and return the current PBOOK archive filename."""
    resp = requests.get(URL, timeout=30)
    resp.raise_for_status()
    tag = BeautifulSoup(resp.text, "html.parser").find(
        href=re.compile(r"LIAIN_01_SIEA.*PBOOK\.zip")
    )
    if tag is None:
        raise RuntimeError("Could not find PBOOK archive link on the listing page")
    return tag.string


def download_zip(filename: str) -> io.BytesIO:
    """Stream the zip archive fully into an in-memory buffer."""
    url = f"{URL}{filename}"
    print(f"Downloading {filename} …")
    resp = requests.get(url, stream=True, timeout=120)
    resp.raise_for_status()

    buf = io.BytesIO()
    downloaded = 0
    for chunk in resp.iter_content(chunk_size=65_536):
        buf.write(chunk)
        downloaded += len(chunk)
    buf.seek(0)
    print(f"Download complete ({downloaded / 1_048_576:.1f} MB in memory)")
    return buf


def _pick_csv(zf: zipfile.ZipFile) -> str:
    """Return the name of the single CSV file inside the archive."""
    csvs = [n for n in zf.namelist() if n.lower().endswith(".csv")]
    if not csvs:
        raise RuntimeError("No CSV file found inside the archive")
    if len(csvs) > 1:
        print(f"Multiple CSVs found, using {csvs[0]}: {csvs}", file=sys.stderr)
    return csvs[0]


def generate_docs(zip_buf: io.BytesIO, transformer: Transformer, run_ts: str):
    """
    Yield Elasticsearch bulk-action dicts, one per CSV row.

    The zip buffer is read sequentially; no full extraction to disk occurs.
    """
    skipped = 0
    with zipfile.ZipFile(zip_buf) as zf:
        csv_name = _pick_csv(zf)
        print(f"Processing {csv_name} …")

        with zf.open(csv_name) as raw:
            # Try UTF-8 with BOM first; most modern exports from French agencies use it.
            try:
                text_stream = io.TextIOWrapper(raw, encoding=CSV_ENCODING, errors="strict")
                reader = csv.DictReader(text_stream, delimiter=";")
                # Peek at header to trigger decode; if it blows up we fall through.
                _ = reader.fieldnames
            except UnicodeDecodeError:
                raw.seek(0)
                text_stream = io.TextIOWrapper(raw, encoding="latin-1", errors="replace")
                reader = csv.DictReader(text_stream, delimiter=";")

            for i, row in enumerate(reader, start=1):
                if len(row) != EXPECTED_FIELDS:
                    skipped += 1
                    if skipped <= 5:
                        print(
                            f"  Row {i}: expected {EXPECTED_FIELDS} fields, got {len(row)} – skipping",
                            file=sys.stderr,
                        )
                    continue

                # ── coordinate transform ──────────────────────────────────────
                try:
                    lat, lon = transformer.transform(
                        row["CoordonneeImmeubleX"], row["CoordonneeImmeubleY"]
                    )
                    row["localisation_immeuble"] = f"{lat},{lon}"
                except (TypeError, Exception):
                    row["localisation_immeuble"] = None

                try:
                    lat, lon = transformer.transform(
                        row["CoordonneePMX"], row["CoordonneePMY"]
                    )
                    row["localisation_pm"] = f"{lat},{lon}"
                except (TypeError, Exception):
                    row["localisation_pm"] = None

                row["@timestamp"] = run_ts

                yield {"_index": ES_INDEX, "_source": row}

                if i % 50_000 == 0:
                    print(f"  … {i:,} rows processed")

    if skipped:
        print(f"Skipped {skipped} malformed rows total.")


def index_docs(es: Elasticsearch, docs):
    success, errors = 0, 0
    try:
        for ok, info in bulk(
            es,
            docs,
            chunk_size=BULK_CHUNK,
            raise_on_error=False,
            request_timeout=60,
        ):
            if ok:
                success += 1
            else:
                errors += 1
                if errors <= 5:
                    print(f"  Index error: {info}", file=sys.stderr)
    except BulkIndexError as exc:
        print(f"Bulk index error: {exc}", file=sys.stderr)

    print(f"Done – indexed {success:,} documents, {errors} errors.")


if __name__ == "__main__":
    es = build_es_client()
    transformer = Transformer.from_crs(2154, 4326)
    run_ts = datetime.now(tz=timezone.utc).isoformat()

    filename = find_archive_filename()
    zip_buf  = download_zip(filename)
    docs     = generate_docs(zip_buf, transformer, run_ts)
    index_docs(es, docs)
