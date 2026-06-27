"""A polite, structure-agnostic recipe scraper for food.upliance.ai.

The site's live markup couldn't be inspected when this prototype was written
(the build environment's egress policy blocks the host), so extraction is
deliberately layered: schema.org JSON-LD first, then Next.js __NEXT_DATA__,
then configurable CSS selectors. Run `python -m scraper.main discover` against
the live site first to see which layer fires, then tune as needed.
"""
