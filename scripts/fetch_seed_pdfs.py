"""One-shot helper: fetch seed-manifest sources into `knowledge/raw_sources/`.

Two modes:

- default — fetch every direct-PDF URL (``.pdf``) from the manifests.
- ``--html`` — fetch the non-PDF (HTML article / vendor page) URLs and
  save them as ``<SOURCE_ID>__<slug>.html``. The chunker handles
  ``.html`` (strips tags), so these become vector-searchable too.

Browser-like behaviour so vendor CDNs don't reject the request:
- a full Chrome header set (UA + Accept + Sec-Fetch-* + ...),
- gzip / deflate response decoding,
- retry with backoff on transient failures,
- ``--insecure`` to skip TLS verification — needed when a corporate
  proxy MITMs HTTPS with a self-signed root (the Infineon failures).

Idempotent — skips files already on disk. Run from the repo root:

    python scripts/fetch_seed_pdfs.py                # PDFs
    python scripts/fetch_seed_pdfs.py --html         # HTML sources
    python scripts/fetch_seed_pdfs.py --html --insecure --retries 4

After running, regenerate the vector index:

    emc-assistant knowledge index

Outputs land in `knowledge/raw_sources/` and are gitignored there.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_DIR = REPO_ROOT / "knowledge" / "seed"
TARGET_DIR = REPO_ROOT / "knowledge" / "raw_sources"

MANIFEST_FILES = (
    SEED_DIR / "baza_pasozyty_pcb_sources.jsonl",
    SEED_DIR / "baza_wiedzy_emc_ltspice_sources.jsonl",
)

REQUEST_TIMEOUT = 40  # seconds per attempt
INTER_REQUEST_DELAY = 0.7  # seconds — be polite to vendor CDNs

# A realistic, current Chrome header set. Vendor CDNs (TI, ADI, Infineon)
# reject the bare urllib UA; this set gets through most of them.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "application/pdf,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
}


def _slug(title: str, max_len: int = 60) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", (title or "").lower()).strip("_")
    return s[:max_len] or "untitled"


def _iter_sources(*, want_pdf: bool):
    """Yield (source_id, url, slug, title) for manifest rows.

    ``want_pdf=True`` → only ``.pdf`` URLs.
    ``want_pdf=False`` → only non-PDF (HTML) URLs.
    Dedups by URL across both manifests.
    """
    seen_urls: set[str] = set()
    for path in MANIFEST_FILES:
        if not path.is_file():
            continue
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sid = (
                    row.get("Source_ID") or row.get("source_id") or row.get("id") or ""
                ).strip()
                url = (row.get("URL") or row.get("url") or "").strip()
                title = (row.get("Title") or row.get("title") or "").strip()
                if not (sid and url):
                    continue
                is_pdf = url.lower().endswith(".pdf")
                if want_pdf != is_pdf:
                    continue
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                yield sid, url, _slug(title), title


def _decode_body(resp, data: bytes) -> bytes:
    """Decompress gzip / deflate response bodies (we send Accept-Encoding)."""
    enc = (resp.headers.get("Content-Encoding") or "").lower()
    if "gzip" in enc:
        try:
            return gzip.decompress(data)
        except OSError:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
                return gz.read()
    if "deflate" in enc:
        try:
            return zlib.decompress(data)
        except zlib.error:
            return zlib.decompress(data, -zlib.MAX_WBITS)
    return data


def _ssl_context(insecure: bool) -> ssl.SSLContext | None:
    if not insecure:
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _classify_body(data: bytes, ctype: str) -> str | None:
    """Return 'pdf' or 'html' from the actual bytes + content-type, else None.

    Content-adaptive: a manifest URL's extension is only a hint. TI's
    ``ti.com/lit/pdf/<id>`` URLs have no ``.pdf`` suffix but serve
    ``application/pdf`` — those are saved as PDFs regardless of which
    mode requested them.
    """
    if data.startswith(b"%PDF-") or "pdf" in ctype:
        return "pdf"
    head = data.lstrip()[:512].lower()
    if "html" in ctype or head.startswith(b"<!doctype html") or head.startswith(b"<html"):
        return "html"
    return None


def _download(
    url: str, stem_dir: Path, stem: str, *, retries: int, insecure: bool
) -> tuple[bool, str, Path | None]:
    """Fetch ``url``; save under ``stem_dir/stem.<ext>`` where the extension
    is decided from the actual content. Returns (success, info, final_path)."""
    ctx = _ssl_context(insecure)
    last_info = "unknown error"
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, headers=BROWSER_HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=ctx) as resp:
                ctype = (resp.headers.get("Content-Type") or "").lower()
                data = _decode_body(resp, resp.read())
            if not data:
                last_info = "empty response"
            else:
                ext = _classify_body(data, ctype)
                if ext is None:
                    last_info = f"unrecognised content (content-type: {ctype or 'unknown'})"
                else:
                    dst = stem_dir / f"{stem}.{ext}"
                    tmp = dst.with_suffix(dst.suffix + ".tmp")
                    tmp.parent.mkdir(parents=True, exist_ok=True)
                    tmp.write_bytes(data)
                    tmp.replace(dst)
                    return True, f"{ext.upper()} {dst.stat().st_size / 1024:.0f} KB", dst
        except urllib.error.HTTPError as exc:
            last_info = f"HTTP {exc.code} {exc.reason}"
        except urllib.error.URLError as exc:
            last_info = f"URL error: {exc.reason}"
        except ssl.SSLError as exc:
            last_info = f"SSL error: {exc} (try --insecure)"
        except Exception as exc:  # noqa: BLE001
            last_info = f"{type(exc).__name__}: {exc}"
        if attempt < retries:
            time.sleep(1.5 * attempt)  # linear backoff
    return False, f"{last_info} (after {retries} attempt(s))", None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--html", action="store_true",
                    help="Fetch non-PDF (HTML) manifest URLs instead of PDFs.")
    ap.add_argument("--insecure", action="store_true",
                    help="Skip TLS verification (corporate-proxy MITM cert chains).")
    ap.add_argument("--retries", type=int, default=3,
                    help="Attempts per URL before giving up (default 3).")
    args = ap.parse_args()

    want_pdf = not args.html
    kind = "PDF" if want_pdf else "HTML/other"
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    items = list(_iter_sources(want_pdf=want_pdf))
    print(f"Found {len(items)} {kind} URL(s) across the seed manifests.")
    print(f"Target dir: {TARGET_DIR}  (content-adaptive: saves .pdf or .html by actual type)")
    if args.insecure:
        print("TLS verification: DISABLED (--insecure)")
    print()

    ok: list[tuple[str, str]] = []
    skipped: list[str] = []
    failed: list[tuple[str, str, str]] = []

    for i, (sid, url, slug, _title) in enumerate(items, start=1):
        stem = f"{sid}__{slug}"
        # Cached if either a .pdf or .html for this stem already exists.
        cached = None
        for ext in ("pdf", "html"):
            cand = TARGET_DIR / f"{stem}.{ext}"
            if cand.is_file() and cand.stat().st_size >= 256:
                cached = cand
                break
        if cached is not None:
            print(f"[{i:3d}/{len(items)}] {sid}: cached  {cached.name}")
            skipped.append(sid)
            continue
        print(f"[{i:3d}/{len(items)}] {sid}: fetching {url}")
        success, info, final = _download(
            url, TARGET_DIR, stem, retries=args.retries, insecure=args.insecure
        )
        if success and final is not None:
            print(f"        -> ok ({info})  {final.name}")
            ok.append((sid, final.name))
        else:
            print(f"        -> FAIL {info}")
            failed.append((sid, url, info))
        time.sleep(INTER_REQUEST_DELAY)

    print()
    print("=" * 64)
    print(f"Summary: {len(ok)} downloaded, {len(skipped)} cached, {len(failed)} failed")
    if failed:
        print("\nFailures (browser-fetch these manually into knowledge/raw_sources/):")
        for sid, url, info in failed:
            print(f"  {sid}  {info}")
            print(f"        {url}")
    print("\nNext: emc-assistant knowledge index")
    return 0 if (ok or skipped) else 2


if __name__ == "__main__":
    sys.exit(main())
