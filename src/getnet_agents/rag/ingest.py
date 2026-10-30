"""Ingestion step of the RAG pipeline (FR-003): URL -> clean markdown with frontmatter.

    python -m getnet_agents.rag.ingest --urls data/knowledge/urls.txt --out data/knowledge/raw

The committed corpus in `data/knowledge/` is a curated snapshot (fetched 2026-10-30, hand-cleaned,
bilingual keywords added) so the service is reproducible without network access. Re-run this script
to refresh the raw pages, then curate.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from datetime import date
from pathlib import Path

import httpx

UA = "getnet-multi-agent-support/1.0 (+https://github.com; RAG ingestion; contact: see README)"


def html_to_markdown(page: str) -> tuple[str, str]:
    """Very small HTML -> markdown converter (no external deps). Returns (title, markdown)."""
    title_m = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    title = html.unescape(title_m.group(1)).strip() if title_m else "untitled"
    page = re.sub(r"<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    page = re.sub(r"<h([1-6])[^>]*>(.*?)</h\1>", lambda m: f"\n\n{'#' * int(m.group(1))} {m.group(2)}\n\n", page,
                  flags=re.S | re.I)
    page = re.sub(r"<li[^>]*>(.*?)</li>", r"\n- \1", page, flags=re.S | re.I)
    page = re.sub(r"</(p|div|section|article|tr|br)>", "\n\n", page, flags=re.I)
    page = re.sub(r"<[^>]+>", " ", page)
    text = html.unescape(page)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return title, text.strip()


def fetch(url: str, client: httpx.Client) -> str:
    resp = client.get(url, headers={"User-Agent": UA}, follow_redirects=True, timeout=20)
    resp.raise_for_status()
    return resp.text


def slugify(url: str) -> str:
    slug = re.sub(r"https?://", "", url).strip("/")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", slug).strip("-").lower()
    return slug[:80] or "index"


def ingest(urls: list[str], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with httpx.Client() as client:
        for url in urls:
            try:
                title, md = html_to_markdown(fetch(url, client))
            except Exception as exc:  # noqa: BLE001 - report and continue with the next URL
                print(f"[ingest] FAILED {url}: {exc}", file=sys.stderr)
                continue
            path = out_dir / f"{slugify(url)}.md"
            path.write_text(
                f"---\ntitle: {title}\nurl: {url}\nlang: pt\nkeywords:\nfetched_at: {date.today().isoformat()}\n---\n\n{md}\n",
                encoding="utf-8",
            )
            written.append(path)
            print(f"[ingest] wrote {path} ({len(md)} chars)")
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch URLs into markdown for the knowledge base")
    parser.add_argument("--urls", required=True, help="text file with one URL per line")
    parser.add_argument("--out", default="data/knowledge/raw")
    args = parser.parse_args(argv)
    urls = [u.strip() for u in Path(args.urls).read_text(encoding="utf-8").splitlines()
            if u.strip() and not u.startswith("#")]
    written = ingest(urls, Path(args.out))
    print(f"[ingest] {len(written)}/{len(urls)} pages written")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
