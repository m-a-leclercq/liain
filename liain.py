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
from elasticsearch.helpers import streaming_bulk
from dotenv import load_dotenv

load_dotenv()

URL = "https://operateurs.liain.fr/ipe/"
ES_HOST    = os.environ["ES_HOST"]
ES_API_KEY = os.environ.get("ES_API_KEY")
ES_USER    = os.environ.get("ES_USERNAME")
ES_PASS    = os.environ.get("ES_PASSWORD")
ES_INDEX   = os.environ.get("ES_INDEX", "liain")

EXPECTED_FIELDS = 65   # current CSV schema column count
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
    """Yield Elasticsearch bulk-action dicts, one per CSV row."""
    with zipfile.ZipFile(zip_buf) as zf:
        csv_name = _pick_csv(zf)
        print(f"Processing {csv_name} …")

        with zf.open(csv_name) as raw:
            try:
                text_stream = io.TextIOWrapper(raw, encoding=CSV_ENCODING, errors="strict")
                reader = csv.DictReader(text_stream, delimiter=";")
                _ = reader.fieldnames  # trigger decode; raises UnicodeDecodeError if encoding wrong
            except UnicodeDecodeError:
                raw.seek(0)
                text_stream = io.TextIOWrapper(raw, encoding="latin-1", errors="replace")
                reader = csv.DictReader(text_stream, delimiter=";")

            actual = len(reader.fieldnames or [])
            if actual != EXPECTED_FIELDS:
                raise RuntimeError(
                    f"CSV header has {actual} columns, expected {EXPECTED_FIELDS}. "
                    "Update EXPECTED_FIELDS if the schema has changed."
                )

            for i, row in enumerate(reader, start=1):
                try:
                    lat, lon = transformer.transform(
                        row["CoordonneeImmeubleX"], row["CoordonneeImmeubleY"]
                    )
                    row["localisation_immeuble"] = f"{lat},{lon}"
                except Exception:
                    row["localisation_immeuble"] = None

                try:
                    lat, lon = transformer.transform(
                        row["CoordonneePMX"], row["CoordonneePMY"]
                    )
                    row["localisation_pm"] = f"{lat},{lon}"
                except Exception:
                    row["localisation_pm"] = None

                row["@timestamp"] = run_ts

                yield {"_index": ES_INDEX, "_source": row}

                if i % 50_000 == 0:
                    print(f"  … {i:,} rows processed")


def index_docs(es: Elasticsearch, docs):
    success, errors = 0, 0
    try:
        for ok, info in streaming_bulk(
            es.options(request_timeout=60),
            docs,
            chunk_size=BULK_CHUNK,
            raise_on_error=False,
        ):
            if ok:
                success += 1
            else:
                errors += 1
                if errors <= 20:
                    print(f"  Index error: {info}", file=sys.stderr)
    except Exception as exc:
        print(
            f"Indexing aborted after {success:,} docs: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise

    if errors:
        print(f"WARNING: {errors:,} documents rejected by ES (first 20 shown above).", file=sys.stderr)
    print(f"Done – indexed {success:,} documents, {errors:,} errors.")


if __name__ == "__main__":
    es = build_es_client()

    info = es.info()
    print(f"Connected to ES cluster '{info['cluster_name']}' v{info['version']['number']}")
    print(f"Target index: {ES_INDEX}")

    transformer = Transformer.from_crs(2154, 4326)
    run_ts = datetime.now(tz=timezone.utc).isoformat()

    filename = find_archive_filename()
    zip_buf  = download_zip(filename)
    docs     = generate_docs(zip_buf, transformer, run_ts)
    index_docs(es, docs)
