# upliance-recipe-scraper

A small, polite recipe scraper prototype targeting [`food.upliance.ai`](https://food.upliance.ai/)
(upliance.ai's "Recipes Digest" portal). Discovers recipe URLs, extracts each
into a normalized JSON record, and writes them to disk.

> **Heads up:** the live site's markup couldn't be inspected when this was
> written — the build environment's egress policy blocks `food.upliance.ai`. So
> extraction is built to be *structure-agnostic* and the URL pattern / CSS
> selectors are **assumptions you should verify locally** (see Tuning below).
> Run it from a machine with normal network access.

## How it works

**Discovery** (`scraper/discover.py`) — find recipe URLs via `sitemap.xml`
(following sitemap indexes), falling back to crawling links off the base page.
Results are filtered by a URL regex (`/recipes?/<slug>` by default).

**Extraction** (`scraper/extract.py`) — for each page, try three strategies and
keep the first usable result:
1. **schema.org JSON-LD** (`<script type="application/ld+json">`) — the gold
   standard most recipe sites emit; handles `@graph`, `HowToStep`/`HowToSection`,
   `ImageObject`, etc.
2. **Next.js `__NEXT_DATA__`** — walks the embedded JSON state for a
   recipe-shaped object (title + ingredients/steps). Covers client-rendered apps.
3. **CSS selectors** — last-resort heuristics in `DEFAULT_SELECTORS`, meant to be
   tuned against the real DOM.

**Politeness** (`scraper/http_client.py`) — honors `robots.txt`, rate-limits
(`--delay`, default 1s), sets a descriptive User-Agent, retries with backoff on
429/5xx. Optional Playwright rendering (`--render`) for JS-heavy pages.

Every strategy emits the same `Recipe` shape (`scraper/models.py`), so the JSON
output schema is stable regardless of how a page was parsed.

## Setup

```bash
cd upliance-recipe-scraper
pip install -r requirements.txt
# Optional, only for --render:
pip install playwright==1.44.0 && playwright install chromium
```

## Usage

```bash
# 1. See what URLs discovery finds (sanity-check the pattern + sitemap first)
python -m scraper.main discover --limit 20

# 2. Debug extraction on a single recipe URL — prints which strategy fired
python -m scraper.main probe https://food.upliance.ai/recipes/<slug>

# 3. Scrape to output/ (one <slug>.json per recipe + index.json)
python -m scraper.main scrape --limit 50 --out output

# JS-rendered? add --render (needs Playwright). Be gentler with --delay 2
python -m scraper.main scrape --render --delay 2
```

### Output

One JSON file per recipe plus an `index.json` manifest. Each record:

```json
{
  "source_url": "https://food.upliance.ai/recipes/paneer-butter-masala",
  "title": "Paneer Butter Masala",
  "description": "Creamy North Indian curry.",
  "image": "https://.../pbm.jpg",
  "cuisine": "North Indian",
  "category": "Main Course",
  "diet": "",
  "tags": ["paneer", "curry", "vegetarian"],
  "prep_time": "PT15M",
  "cook_time": "PT25M",
  "total_time": "",
  "servings": "4 servings",
  "ingredients": ["200g paneer", "2 tomatoes", "1 tbsp butter"],
  "steps": ["Blend tomatoes.", "Simmer with butter.", "Add paneer."],
  "extracted_via": "json-ld"
}
```

## Tuning against the live site

Because the markup wasn't verifiable at build time, run `discover` and `probe`
first, then adjust if needed:

- **No URLs from `discover`?** The sitemap may be missing or recipe URLs may use
  a different path. Edit `DEFAULT_RECIPE_PATTERN` in `scraper/discover.py`, or
  pass a different `--base`.
- **`probe` says "No recipe extracted"?** Check whether the page is
  JS-rendered — retry with `--render`. If it's rendered but still empty, open
  dev tools, find the recipe markup, and update `DEFAULT_SELECTORS` in
  `scraper/extract.py` (or the loose-key names in `_recipe_from_loose` if the
  data ships as JSON).
- **`probe` works but fields are blank?** The `extracted_via` field tells you
  which strategy ran — fix that strategy's mapping.

## Tests

Offline unit tests cover all three extraction strategies, strategy precedence,
JSON-LD `@graph`/section flattening, and the URL pattern — no network needed:

```bash
pytest -q
```

## Notes on responsible use

This is a personal/educational prototype. It respects `robots.txt` and
rate-limits by default. Recipe instruction text is copyrightable even where bare
ingredient lists generally aren't — keep scraped data for personal use, don't
redistribute, and don't hammer the site. Review upliance.ai's Terms of Service
before any non-trivial run.
