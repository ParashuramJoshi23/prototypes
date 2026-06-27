"""Offline extraction tests against representative HTML fixtures.

These don't touch the network: they feed hand-built HTML (mirroring the three
shapes the scraper handles) through extract() and assert the normalized output.
"""

import json

from scraper.extract import extract
from scraper.discover import DEFAULT_RECIPE_PATTERN

URL = "https://food.upliance.ai/recipes/paneer-butter-masala"


def test_json_ld_recipe():
    html = """
    <html><head>
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "Recipe",
      "name": "Paneer Butter Masala",
      "description": "Creamy North Indian curry.",
      "image": {"@type": "ImageObject", "url": "https://img/pbm.jpg"},
      "recipeCuisine": "North Indian",
      "recipeCategory": "Main Course",
      "keywords": "paneer, curry, vegetarian",
      "prepTime": "PT15M",
      "cookTime": "PT25M",
      "recipeYield": "4 servings",
      "recipeIngredient": ["200g paneer", "2 tomatoes", "1 tbsp butter"],
      "recipeInstructions": [
        {"@type": "HowToStep", "text": "Blend tomatoes."},
        {"@type": "HowToStep", "text": "Simmer with butter."},
        {"@type": "HowToStep", "text": "Add paneer."}
      ]
    }
    </script></head><body></body></html>
    """
    r = extract(html, URL)
    assert r is not None
    assert r.extracted_via == "json-ld"
    assert r.title == "Paneer Butter Masala"
    assert r.image == "https://img/pbm.jpg"
    assert r.cuisine == "North Indian"
    assert r.tags == ["paneer", "curry", "vegetarian"]
    assert r.ingredients == ["200g paneer", "2 tomatoes", "1 tbsp butter"]
    assert r.steps == ["Blend tomatoes.", "Simmer with butter.", "Add paneer."]
    assert r.is_usable()


def test_json_ld_in_graph_with_sections():
    """@graph wrapping + HowToSection nesting + string instructions."""
    html = """
    <script type="application/ld+json">
    {"@context":"https://schema.org","@graph":[
      {"@type":"WebPage","name":"ignore me"},
      {"@type":["Recipe"],"name":"Dal Tadka",
       "recipeIngredient":["1 cup dal","spices"],
       "recipeInstructions":[
         {"@type":"HowToSection","itemListElement":[
            {"@type":"HowToStep","text":"Boil dal."}]},
         "Temper with spices."]}
    ]}
    </script>
    """
    r = extract(html, URL)
    assert r.title == "Dal Tadka"
    assert r.steps == ["Boil dal.", "Temper with spices."]


def test_next_data_recipe():
    payload = {
        "props": {"pageProps": {"recipe": {
            "title": "Masala Dosa",
            "description": "Crispy fermented crepe.",
            "imageUrl": "https://img/dosa.jpg",
            "cuisine": "South Indian",
            "mealType": "Breakfast",
            "tags": ["dosa", "vegan"],
            "ingredients": ["2 cups rice batter", "potato filling"],
            "steps": [{"text": "Spread batter."}, {"text": "Add filling."}],
        }}}
    }
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
    r = extract(html, URL)
    assert r is not None
    assert r.extracted_via == "next-data"
    assert r.title == "Masala Dosa"
    assert r.category == "Breakfast"
    assert r.tags == ["dosa", "vegan"]
    assert r.steps == ["Spread batter.", "Add filling."]


def test_css_fallback():
    html = """
    <html><head>
      <meta name="description" content="Tangy lentil soup.">
      <meta property="og:image" content="https://img/rasam.jpg">
    </head><body>
      <h1>Rasam</h1>
      <ul class="ingredients"><li>Tamarind</li><li>Tomato</li></ul>
      <ol class="instructions"><li>Boil.</li><li>Season.</li></ol>
      <div class="tags"><a rel="tag">soup</a></div>
    </body></html>
    """
    r = extract(html, URL)
    assert r is not None
    assert r.extracted_via == "css"
    assert r.title == "Rasam"
    assert r.description == "Tangy lentil soup."
    assert r.image == "https://img/rasam.jpg"
    assert r.ingredients == ["Tamarind", "Tomato"]
    assert r.steps == ["Boil.", "Season."]


def test_no_recipe_returns_none():
    assert extract("<html><body><p>Just a blog post.</p></body></html>", URL) is None


def test_strategy_precedence_prefers_json_ld():
    """When both JSON-LD and CSS content exist, JSON-LD wins."""
    html = """
    <script type="application/ld+json">
    {"@type":"Recipe","name":"From LD","recipeIngredient":["a"],
     "recipeInstructions":["do it"]}
    </script>
    <h1>From CSS</h1>
    <ul class="ingredients"><li>b</li></ul>
    """
    r = extract(html, URL)
    assert r.title == "From LD"
    assert r.extracted_via == "json-ld"


def test_recipe_url_pattern():
    assert DEFAULT_RECIPE_PATTERN.search("https://food.upliance.ai/recipes/paneer")
    assert DEFAULT_RECIPE_PATTERN.search("https://food.upliance.ai/recipe/dal/")
    assert not DEFAULT_RECIPE_PATTERN.search("https://food.upliance.ai/about")
    assert not DEFAULT_RECIPE_PATTERN.search("https://food.upliance.ai/recipes/")
