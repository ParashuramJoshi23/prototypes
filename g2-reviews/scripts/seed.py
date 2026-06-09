"""
Quick seed script — creates 2 products + 50 reviews for local testing.
Usage: python scripts/seed.py
"""
import asyncio
import random
import asyncpg

DSN = "postgresql://g2user:g2pass@localhost:5435/g2reviews"

PRODUCTS = [
    {"name": "Salesforce CRM", "category": "CRM", "slug": "salesforce-crm"},
    {"name": "HubSpot Marketing Hub", "category": "Marketing", "slug": "hubspot-marketing-hub"},
]

NAMES = ["Alice Chen", "Bob Martinez", "Carol Singh", "David Kim", "Eva Rossi",
         "Frank Müller", "Grace Okafor", "Hina Tanaka"]
TITLES = ["VP Sales", "Marketing Manager", "CTO", "Product Owner", "Software Engineer", None]
COMPANIES = ["Acme Corp", "TechStart", "Globex", "Initech", "Umbrella Ltd"]
PROS_POOL = ["Easy to use", "Great support", "Powerful features", "Good integrations", "Affordable"]
CONS_POOL = ["Steep learning curve", "Expensive", "Slow support", "Limited customisation", "Mobile app needs work"]


async def main():
    conn = await asyncpg.connect(DSN)

    product_ids = []
    for p in PRODUCTS:
        row = await conn.fetchrow(
            """
            INSERT INTO products (name, category, slug)
            VALUES ($1,$2,$3)
            ON CONFLICT (slug) DO UPDATE SET name=EXCLUDED.name
            RETURNING id
            """,
            p["name"], p["category"], p["slug"],
        )
        product_ids.append(row["id"])
        print(f"  product {p['slug']}  id={row['id']}")

    for i in range(50):
        product_id = random.choice(product_ids)
        await conn.execute(
            """
            INSERT INTO reviews
                (product_id, reviewer_name, reviewer_title, reviewer_company,
                 rating, title, body, pros, cons, verified, helpful_count)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            """,
            product_id,
            random.choice(NAMES),
            random.choice(TITLES),
            random.choice(COMPANIES),
            random.randint(1, 5),
            f"Review #{i+1} — {'Great' if i % 3 == 0 else 'Average'} product",
            "This is a detailed review body. " * random.randint(3, 8),
            random.choice(PROS_POOL),
            random.choice(CONS_POOL),
            random.random() > 0.3,
            random.randint(0, 120),
        )

    await conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_product_review_stats")
    await conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_top_reviews")
    await conn.close()
    print("Seeded 2 products + 50 reviews. Materialized views refreshed.")


if __name__ == "__main__":
    asyncio.run(main())
