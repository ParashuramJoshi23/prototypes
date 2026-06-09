-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Products table
CREATE TABLE IF NOT EXISTS products (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(255) NOT NULL,
    category    VARCHAR(255),
    slug        VARCHAR(255) UNIQUE NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Reviews table
CREATE TABLE IF NOT EXISTS reviews (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id       UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    reviewer_name    VARCHAR(255) NOT NULL,
    reviewer_title   VARCHAR(255),
    reviewer_company VARCHAR(255),
    rating           SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    title            VARCHAR(500) NOT NULL,
    body             TEXT NOT NULL,
    pros             TEXT,
    cons             TEXT,
    verified         BOOLEAN NOT NULL DEFAULT FALSE,
    helpful_count    INTEGER NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_reviews_product_id        ON reviews(product_id);
CREATE INDEX IF NOT EXISTS idx_reviews_product_rating    ON reviews(product_id, rating);
CREATE INDEX IF NOT EXISTS idx_reviews_product_created   ON reviews(product_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reviews_verified          ON reviews(product_id, verified) WHERE verified = TRUE;

-- Materialized view: per-product rating aggregates
-- Refreshed explicitly (or via background job) after writes
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_product_review_stats AS
SELECT
    p.id                                                              AS product_id,
    p.name                                                            AS product_name,
    p.category,
    COUNT(r.id)                                                       AS total_reviews,
    ROUND(AVG(r.rating)::NUMERIC, 2)                                  AS avg_rating,
    COUNT(r.id) FILTER (WHERE r.rating = 5)                           AS five_star,
    COUNT(r.id) FILTER (WHERE r.rating = 4)                           AS four_star,
    COUNT(r.id) FILTER (WHERE r.rating = 3)                           AS three_star,
    COUNT(r.id) FILTER (WHERE r.rating = 2)                           AS two_star,
    COUNT(r.id) FILTER (WHERE r.rating = 1)                           AS one_star,
    COUNT(r.id) FILTER (WHERE r.verified = TRUE)                      AS verified_reviews,
    MAX(r.created_at)                                                  AS latest_review_at
FROM products p
LEFT JOIN reviews r ON r.product_id = p.id
GROUP BY p.id, p.name, p.category;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_product_review_stats_pk
    ON mv_product_review_stats(product_id);

-- Materialized view: recent top reviews per product (top 10 by helpful_count)
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_top_reviews AS
SELECT *
FROM (
    SELECT
        r.*,
        ROW_NUMBER() OVER (PARTITION BY r.product_id ORDER BY r.helpful_count DESC, r.created_at DESC) AS rn
    FROM reviews r
    WHERE r.verified = TRUE
) ranked
WHERE rn <= 10;

CREATE INDEX IF NOT EXISTS idx_mv_top_reviews_product ON mv_top_reviews(product_id);

-- Updated-at trigger
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_reviews_updated_at ON reviews;
CREATE TRIGGER trg_reviews_updated_at
    BEFORE UPDATE ON reviews
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
