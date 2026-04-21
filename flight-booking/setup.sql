DROP TABLE IF EXISTS seats CASCADE;
CREATE TABLE seats (id SERIAL PRIMARY KEY, booked_by TEXT);
INSERT INTO seats (id) SELECT generate_series(1, 120);
