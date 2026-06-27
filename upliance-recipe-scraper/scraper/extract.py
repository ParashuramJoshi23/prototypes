"""Turn a recipe page's HTML into a Recipe, trying three strategies in order.

1. schema.org JSON-LD  -> the gold standard; most recipe CMSs emit it.
2. Next.js __NEXT_DATA__ -> for client-rendered apps that ship state as JSON.
3. CSS selectors        -> last resort; selectors live in DEFAULT_SELECTORS and
                            are meant to be tuned against the real markup.

The first strategy that yields a usable Recipe wins.
"""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from .models import Recipe

# Tune these against the live page (inspect-element on food.upliance.ai) if the
# JSON-LD / Next.js layers don't fire. Each value is a CSS selector.
DEFAULT_SELECTORS = {
    "title": "h1",
    "description": "meta[name=description]",  # read from `content`
    "image": "meta[property='og:image']",     # read from `content`
    "ingredients": "[class*=ingredient] li, ul.ingredients li",
    "steps": "[class*=instruction] li, [class*=step] li, ol.instructions li",
    "tags": "[class*=tag] a, [rel=tag]",
}


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def extract(html: str, url: str, selectors: dict | None = None) -> Recipe | None:
    """Return the first usable Recipe found in `html`, or None."""
    soup = BeautifulSoup(html, "lxml")
    for strategy in (_from_json_ld, _from_next_data, _from_css):
        recipe = strategy(soup, url, selectors or DEFAULT_SELECTORS)
        if recipe and recipe.is_usable():
            return recipe
    return None


# --------------------------------------------------------------------------
# Strategy 1: schema.org/Recipe JSON-LD
# --------------------------------------------------------------------------

def _from_json_ld(soup: BeautifulSoup, url: str, _selectors: dict) -> Recipe | None:
    for node in _iter_json_ld(soup):
        if _is_recipe_node(node):
            return _recipe_from_ld(node, url)
    return None


def _iter_json_ld(soup: BeautifulSoup):
    """Yield every JSON-LD object, flattening @graph and top-level lists."""
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                if "@graph" in item:
                    stack.extend(_as_list(item["@graph"]))
                yield item


def _is_recipe_node(node: dict) -> bool:
    types = _as_list(node.get("@type", []))
    return any(str(t).lower() == "recipe" for t in types)


def _recipe_from_ld(node: dict, url: str) -> Recipe:
    return Recipe(
        source_url=url,
        title=_clean(node.get("name", "")),
        description=_clean(node.get("description", "")),
        image=_first_image(node.get("image")),
        cuisine=_clean(_join(node.get("recipeCuisine"))),
        category=_clean(_join(node.get("recipeCategory"))),
        tags=[_clean(k) for k in _split_keywords(node.get("keywords"))],
        prep_time=_clean(node.get("prepTime", "")),
        cook_time=_clean(node.get("cookTime", "")),
        total_time=_clean(node.get("totalTime", "")),
        servings=_clean(_join(node.get("recipeYield"))),
        ingredients=[_clean(i) for i in _as_list(node.get("recipeIngredient")) if _clean(i)],
        steps=_ld_steps(node.get("recipeInstructions")),
        extracted_via="json-ld",
    )


def _ld_steps(instructions) -> list[str]:
    """recipeInstructions can be a string, a list of strings, HowToStep dicts,
    or HowToSection dicts that nest further steps. Flatten them all to text."""
    steps: list[str] = []
    for item in _as_list(instructions):
        if isinstance(item, str):
            text = _clean(item)
            if text:
                steps.append(text)
        elif isinstance(item, dict):
            itype = str(_join(item.get("@type", ""))).lower()
            if "howtosection" in itype:
                steps.extend(_ld_steps(item.get("itemListElement")))
            else:
                text = _clean(item.get("text") or item.get("name") or "")
                if text:
                    steps.append(text)
    return steps


# --------------------------------------------------------------------------
# Strategy 2: Next.js __NEXT_DATA__
# --------------------------------------------------------------------------

def _from_next_data(soup: BeautifulSoup, url: str, _selectors: dict) -> Recipe | None:
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not (script.string or script.get_text()):
        return None
    try:
        data = json.loads(script.string or script.get_text())
    except json.JSONDecodeError:
        return None
    node = _find_recipe_like(data)
    if not node:
        return None
    return _recipe_from_loose(node, url)


def _find_recipe_like(data, _depth: int = 0):
    """Walk arbitrary nested JSON for a dict that looks like a recipe: it has a
    title-ish key plus ingredients or steps. Returns the first match."""
    if _depth > 12:
        return None
    if isinstance(data, dict):
        keys = {k.lower() for k in data.keys()}
        has_title = keys & {"title", "name", "recipename"}
        has_body = keys & {"ingredients", "steps", "instructions", "recipeingredient"}
        if has_title and has_body:
            return data
        for value in data.values():
            found = _find_recipe_like(value, _depth + 1)
            if found:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _find_recipe_like(value, _depth + 1)
            if found:
                return found
    return None


def _recipe_from_loose(node: dict, url: str) -> Recipe:
    """Build a Recipe from a loosely-keyed dict (Next.js state / arbitrary API)."""
    get = lambda *names: _first_present(node, names)
    return Recipe(
        source_url=url,
        title=_clean(get("title", "name", "recipeName")),
        description=_clean(get("description", "summary")),
        image=_first_image(get("image", "imageUrl", "thumbnail")),
        cuisine=_clean(_join(get("cuisine", "recipeCuisine"))),
        category=_clean(_join(get("category", "recipeCategory", "mealType"))),
        diet=_clean(_join(get("diet", "dietary", "dietType"))),
        tags=[_clean(t) for t in _as_list(get("tags", "keywords")) if _clean(_join(t))],
        prep_time=_clean(_join(get("prepTime", "prep_time"))),
        cook_time=_clean(_join(get("cookTime", "cook_time"))),
        total_time=_clean(_join(get("totalTime", "total_time"))),
        servings=_clean(_join(get("servings", "recipeYield", "yield"))),
        ingredients=_loose_lines(get("ingredients", "recipeIngredient")),
        steps=_loose_lines(get("steps", "instructions", "recipeInstructions")),
        extracted_via="next-data",
    )


def _loose_lines(value) -> list[str]:
    """Coerce a list of strings or objects ({text|name|step|...}) into strings."""
    lines: list[str] = []
    for item in _as_list(value):
        if isinstance(item, str):
            text = _clean(item)
        elif isinstance(item, dict):
            text = _clean(
                item.get("text")
                or item.get("name")
                or item.get("step")
                or item.get("description")
                or item.get("ingredient")
                or ""
            )
        else:
            text = ""
        if text:
            lines.append(text)
    return lines


# --------------------------------------------------------------------------
# Strategy 3: CSS selectors (best-effort fallback)
# --------------------------------------------------------------------------

def _from_css(soup: BeautifulSoup, url: str, selectors: dict) -> Recipe | None:
    title = _select_text(soup, selectors.get("title", ""))
    ingredients = _select_all_text(soup, selectors.get("ingredients", ""))
    steps = _select_all_text(soup, selectors.get("steps", ""))
    if not title or not (ingredients or steps):
        return None
    return Recipe(
        source_url=url,
        title=title,
        description=_select_attr(soup, selectors.get("description", ""), "content"),
        image=_select_attr(soup, selectors.get("image", ""), "content"),
        tags=_select_all_text(soup, selectors.get("tags", "")),
        ingredients=ingredients,
        steps=steps,
        extracted_via="css",
    )


def _select_text(soup, selector: str) -> str:
    if not selector:
        return ""
    el = soup.select_one(selector)
    return _clean(el.get_text()) if el else ""


def _select_attr(soup, selector: str, attr: str) -> str:
    if not selector:
        return ""
    el = soup.select_one(selector)
    return _clean(el.get(attr, "")) if el else ""


def _select_all_text(soup, selector: str) -> list[str]:
    if not selector:
        return []
    out, seen = [], set()
    for el in soup.select(selector):
        text = _clean(el.get_text())
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _join(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v)
    return "" if value is None else str(value)


def _clean(text) -> str:
    return re.sub(r"\s+", " ", str(text)).strip() if text else ""


def _first_present(node: dict, names):
    lowered = {k.lower(): v for k, v in node.items()}
    for name in names:
        if name.lower() in lowered and lowered[name.lower()] not in (None, "", [], {}):
            return lowered[name.lower()]
    return None


def _first_image(value) -> str:
    """image may be a URL string, a list, or an ImageObject dict."""
    for item in _as_list(value):
        if isinstance(item, str) and item:
            return _clean(item)
        if isinstance(item, dict):
            url = item.get("url") or item.get("contentUrl")
            if url:
                return _clean(url)
    return ""


def _split_keywords(value) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str):
        return [k for k in re.split(r"\s*,\s*", value) if k]
    return []
