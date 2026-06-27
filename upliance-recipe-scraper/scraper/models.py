"""Normalized recipe model shared by every extraction strategy."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass
class Recipe:
    """A single normalized recipe.

    Every extractor (JSON-LD, Next.js data, CSS heuristics) produces this same
    shape so the output schema is stable regardless of how the page was parsed.
    """

    source_url: str
    title: str = ""
    description: str = ""
    image: str = ""
    cuisine: str = ""
    category: str = ""
    diet: str = ""
    tags: list[str] = field(default_factory=list)
    prep_time: str = ""
    cook_time: str = ""
    total_time: str = ""
    servings: str = ""
    ingredients: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    # Which strategy produced this record ("json-ld" | "next-data" | "css").
    extracted_via: str = ""

    def is_usable(self) -> bool:
        """A record is worth keeping if it has a title and some real content."""
        return bool(self.title) and bool(self.ingredients or self.steps)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
