"""
Bulk-loads 1,000,000 reviews across 10 products using asyncpg COPY
(binary protocol — fastest possible Postgres insertion path).
Refreshes materialized views after load.
"""
import asyncio
import random
import time
import uuid
from datetime import datetime, timezone

import asyncpg

DSN = "postgresql://g2user:g2pass@localhost:5432/g2reviews"

PRODUCTS = [
    ("Salesforce CRM",           "CRM",          "salesforce-crm"),
    ("HubSpot Marketing Hub",    "Marketing",     "hubspot-marketing"),
    ("Zendesk Support",          "Support",       "zendesk-support"),
    ("Slack",                    "Collaboration", "slack"),
    ("Jira Software",            "Project Mgmt",  "jira-software"),
    ("Zoom",                     "Video Conf",    "zoom"),
    ("Notion",                   "Productivity",  "notion"),
    ("Figma",                    "Design",        "figma"),
    ("GitHub",                   "Dev Tools",     "github-app"),
    ("Datadog",                  "Monitoring",    "datadog"),
]

TITLES = ["VP Sales", "Marketing Manager", "CTO", "Product Owner", "SWE",
          "DevOps Lead", "Designer", "CEO", "COO", "Customer Success"]
COMPANIES = ["Acme Corp", "TechStart", "Globex", "Initech", "Umbrella Ltd",
             "Wayne Ent", "Stark Industries", "Dunder Mifflin", "Pied Piper", "Hooli"]
NAMES = ["Alice Chen", "Bob Martinez", "Carol Singh", "David Kim", "Eva Rossi",
         "Frank Müller", "Grace Okafor", "Hina Tanaka", "Ivan Petrov", "Julia Santos"]
PROS = ["Easy to use", "Great support", "Powerful features", "Good integrations",
        "Affordable", "Scales well", "Beautiful UI", "Fast setup", "Great docs", "Reliable"]
CONS = ["Steep learning curve", "Expensive", "Slow support", "Limited customisation",
        "Mobile app lacking", "No offline mode", "Complex billing", "Buggy exports",
        "Weak search", "Missing webhooks"]

TOTAL = 1_000_000
BATCH = 5_000


async def main():
    conn = await asyncpg.connect(DSN)

    # Insert products
    product_ids = []
    for name, cat, slug in PRODUCTS:
        row = await conn.fetchrow(
            """
            INSERT INTO products (name, category, slug)
            VALUES ($1,$2,$3)
            ON CONFLICT (slug) DO UPDATE SET name=EXCLUDED.name
            RETURNING id
            """,
            name, cat, slug,
        )
        product_ids.append(row["id"])
    print(f"  {len(product_ids)} products ready")

    # Bulk-load reviews via COPY
    rng = random.Random(42)
    now = datetime.now(timezone.utc)

    print(f"  Inserting {TOTAL:,} reviews in batches of {BATCH:,}...")
    t0 = time.perf_counter()

    inserted = 0
    while inserted < TOTAL:
        batch_size = min(BATCH, TOTAL - inserted)
        records = []
        for _ in range(batch_size):
            records.append((
                uuid.uuid4(),                          # id
                rng.choice(product_ids),               # product_id
                rng.choice(NAMES),                     # reviewer_name
                rng.choice(TITLES),                    # reviewer_title
                rng.choice(COMPANIES),                 # reviewer_company
                rng.randint(1, 5),                     # rating
                f"Review #{inserted + len(records) + 1}: {'Great' if rng.random()>0.5 else 'Average'} product",
                "Detailed review body text. " * rng.randint(3, 8),  # body
                rng.choice(PROS),                      # pros
                rng.choice(CONS),                      # cons
                rng.random() > 0.3,                    # verified
                rng.randint(0, 200),                   # helpful_count
                now,                                   # created_at
                now,                                   # updated_at
            ))

        await conn.copy_records_to_table(
            "reviews",
            records=records,
            columns=["id", "product_id", "reviewer_name", "reviewer_title",
                     "reviewer_company", "rating", "title", "body",
                     "pros", "cons", "verified", "helpful_count",
                     "created_at", "updated_at"],
        )
        inserted += batch_size
        elapsed = time.perf_counter() - t0
        rate = inserted / elapsed
        print(f"    {inserted:>9,} / {TOTAL:,}  ({rate:,.0f} rows/s)", end="\r")

    elapsed = time.perf_counter() - t0
    print(f"\n  Done: {TOTAL:,} rows in {elapsed:.1f}s  ({TOTAL/elapsed:,.0f} rows/s)")

    # Refresh materialized views
    print("  Refreshing materialized views...", end=" ", flush=True)
    t1 = time.perf_counter()
    await conn.execute("REFRESH MATERIALIZED VIEW mv_product_review_stats")
    await conn.execute("REFRESH MATERIALIZED VIEW mv_top_reviews")
    print(f"{time.perf_counter()-t1:.2f}s")

    # Quick sanity check
    row = await conn.fetchrow("SELECT COUNT(*) FROM reviews")
    print(f"  Total reviews in DB: {row['count']:,}")
    rows = await conn.fetch("SELECT product_id, COUNT(*) FROM reviews GROUP BY product_id ORDER BY 2 DESC LIMIT 3")
    for r in rows:
        print(f"    product {r['product_id']}  →  {r['count']:,} reviews")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
