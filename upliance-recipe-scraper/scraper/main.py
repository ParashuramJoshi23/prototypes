"""CLI entry point.

    python -m scraper.main discover [--limit N]
    python -m scraper.main scrape   [--limit N] [--out DIR] [--render]
    python -m scraper.main probe URL          # debug a single page's extraction

`discover` lists recipe URLs (use it first to sanity-check the URL pattern and
whether a sitemap exists). `scrape` extracts each recipe to a JSON file plus a
combined index.json. `probe` shows which extraction strategy fires on one URL.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .discover import DEFAULT_RECIPE_PATTERN, discover
from .extract import extract
from .http_client import Client

BASE_URL = "https://food.upliance.ai/"


def _slug(url: str) -> str:
    tail = url.rstrip("/").split("/")[-1] or "recipe"
    return re.sub(r"[^a-z0-9._-]+", "-", tail.lower()).strip("-") or "recipe"


def cmd_discover(args) -> int:
    with _client(args) as client:
        urls = discover(client, args.base, limit=args.limit)
    for u in urls:
        print(u)
    print(f"\n{len(urls)} recipe URL(s) found.", file=sys.stderr)
    if not urls:
        print(
            "No URLs matched. Check the sitemap exists and that --pattern fits "
            "the real recipe URL shape (see scraper/discover.py).",
            file=sys.stderr,
        )
    return 0


def cmd_scrape(args) -> int:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    index = []
    with _client(args) as client:
        urls = discover(client, args.base, limit=args.limit)
        print(f"Discovered {len(urls)} recipe URL(s).", file=sys.stderr)
        for i, url in enumerate(urls, 1):
            try:
                html = client.fetch(url)
            except Exception as e:  # noqa: BLE001 - keep going on per-page errors
                print(f"[{i}/{len(urls)}] FETCH FAIL {url}: {e}", file=sys.stderr)
                continue
            if not html:
                print(f"[{i}/{len(urls)}] SKIP (robots/empty) {url}", file=sys.stderr)
                continue
            recipe = extract(html, url)
            if not recipe:
                print(f"[{i}/{len(urls)}] NO RECIPE {url}", file=sys.stderr)
                continue
            path = out_dir / f"{_slug(url)}.json"
            path.write_text(recipe.to_json(), encoding="utf-8")
            index.append({"title": recipe.title, "url": url, "file": path.name,
                          "via": recipe.extracted_via})
            print(f"[{i}/{len(urls)}] OK ({recipe.extracted_via}) {recipe.title}",
                  file=sys.stderr)
    (out_dir / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote {len(index)} recipe(s) to {out_dir}/", file=sys.stderr)
    return 0


def cmd_probe(args) -> int:
    with _client(args) as client:
        html = client.fetch(args.url)
    if not html:
        print("No HTML (blocked by robots.txt or empty response).", file=sys.stderr)
        return 1
    recipe = extract(html, args.url)
    if not recipe:
        print("No recipe extracted by any strategy.", file=sys.stderr)
        return 1
    print(recipe.to_json())
    return 0


def _client(args) -> Client:
    return Client(
        delay=args.delay,
        respect_robots=not args.ignore_robots,
        render=getattr(args, "render", False),
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="scraper.main", description=__doc__)
    p.add_argument("--base", default=BASE_URL, help="Base URL to scrape")
    p.add_argument("--delay", type=float, default=1.0, help="Seconds between requests")
    p.add_argument("--ignore-robots", action="store_true",
                   help="Skip robots.txt checks (use responsibly)")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("discover", help="List recipe URLs")
    d.add_argument("--limit", type=int, default=None)
    d.set_defaults(func=cmd_discover)

    s = sub.add_parser("scrape", help="Scrape recipes to JSON")
    s.add_argument("--limit", type=int, default=None)
    s.add_argument("--out", default="output")
    s.add_argument("--render", action="store_true",
                   help="Render JS with Playwright (requires playwright install)")
    s.set_defaults(func=cmd_scrape)

    pr = sub.add_parser("probe", help="Debug extraction on one URL")
    pr.add_argument("url")
    pr.add_argument("--render", action="store_true")
    pr.set_defaults(func=cmd_probe)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
