# Hashtag Service

Demonstrates hashtag counting, top-100 post retrieval, pre-signed S3 media uploads, and async event processing via Kafka.

---

## Architecture

```
Client
  │
  │  POST /posts            POST /posts/{id}/confirm
  │  (get pre-signed URL)   (activate post)
  │                │
  ▼                ▼
┌──────────────────────────┐        ┌──────────────────────┐
│      FastAPI (app)       │──────▶│   PostgreSQL          │
│                          │       │   users               │
│  /users                  │       │   posts               │
│  /posts                  │       │   hashtags            │
│  /hashtags/{tag}/count   │       │   post_hashtags       │
│  /hashtags/{tag}/posts   │       │   notifications       │
│  /notifications/{uid}    │       └──────────────────────┘
└────────────┬─────────────┘
             │ Kafka produce
             │ post.created
             ▼
┌──────────────────────────┐        ┌──────────────────────┐
│   Kafka Consumer         │──────▶│   Redis               │
│                          │       │   hashtag:{tag}:count │
│  post.created            │       │   hashtag:{tag}:top100│
│    → hashtag.process     │       │   hashtag:{tag}:posts │
│                          │       └──────────────────────┘
│  hashtag.process         │
│    → upsert hashtag      │        ┌──────────────────────┐
│    → increment count     │──────▶│   PostgreSQL          │
│    → link post           │       │   (writes)            │
│    → invalidate cache    │       └──────────────────────┘
│    → hashtag.created /   │
│      hashtag.incremented │
│    → notification.inapp  │
│                          │
│  notification.inapp      │
│    → insert notification │
└──────────────────────────┘

Client (direct S3 upload):
  POST /posts  ──▶  app returns pre-signed PUT URL
  Client  ─────────────────────────────▶  S3 (LocalStack)
  POST /posts/{id}/confirm  ──▶  app activates post
```

---

## Kafka Topics

| Topic                  | Producer       | Consumer          | Purpose                                    |
|------------------------|----------------|-------------------|--------------------------------------------|
| `post.created`         | API (app)      | Consumer          | Fired when a post goes active              |
| `hashtag.process`      | Consumer       | Consumer          | One event per hashtag extracted from post  |
| `hashtag.created`      | Consumer       | (observability)   | New hashtag coined                         |
| `hashtag.incremented`  | Consumer       | (observability)   | Existing hashtag count bumped              |
| `notification.inapp`   | Consumer       | Consumer          | Trigger in-app notification creation       |

---

## Pre-signed URL Flow

```
1. Client  POST /posts  { caption, media_filename, media_content_type }
           ← { post_id, upload_url (S3 pre-signed PUT), s3_key, expires_in }

2. Client  PUT <upload_url>  <binary file>      ← direct to S3, no app involved

3. Client  POST /posts/{post_id}/confirm
           ← PostOut (status: active)
           → fires post.created on Kafka
```

**Why two S3 endpoints?**

Inside Docker Compose the app reaches LocalStack via `http://localstack:4566` (docker-internal hostname). Pre-signed URLs handed to the browser must use `http://localhost:4566` — the hostname the client machine can actually reach.

| Env var               | Value in Compose              | Used for                          |
|-----------------------|-------------------------------|-----------------------------------|
| `S3_ENDPOINT_URL`     | `http://localstack:4566`      | App-to-S3 API calls               |
| `PRESIGN_ENDPOINT_URL`| `http://localhost:4566`       | Hostname embedded in pre-signed URLs |

---

## Database Schema

```
users
  id (PK, UUID)
  username (unique)
  email (unique)
  created_at

posts
  id (PK, UUID)
  user_id (FK → users)
  caption (TEXT)
  media_s3_key (nullable)       ← S3 object key for media uploads
  status  draft | active | failed
  created_at, updated_at

hashtags
  id (PK, UUID)
  tag (unique, lowercase, no #)
  post_count (BIGINT)           ← denormalised counter, atomically incremented
  created_at, updated_at

post_hashtags                   ← many-to-many join, populated by consumer
  post_id (FK → posts)
  hashtag_id (FK → hashtags)
  created_at

notifications
  id (PK, UUID)
  user_id (FK → users)
  type        hashtag_created | …
  title, body
  is_read (BOOLEAN)
  payload (JSONB)               ← tag, hashtag_id, post_id, etc.
  created_at
```

---

## Redis Cache

| Key                      | Type        | TTL        | Content                              |
|--------------------------|-------------|------------|--------------------------------------|
| `hashtag:{tag}:count`    | String      | 5 min      | Cached post_count integer            |
| `hashtag:{tag}:top100`   | String      | 2 min      | JSON-serialised list of top-100 posts|
| `hashtag:{tag}:posts`    | Sorted Set  | no TTL     | post_id → unix timestamp, capped 100 |

The sorted set is an incrementally-updated index maintained by the consumer on every `hashtag.process` event. It survives service restarts. The JSON blob cache (`top100`) is computed from Postgres on miss and then warm for 2 minutes.

---

## API Reference

```
POST  /users                          Create / get user
GET   /users/{user_id}                Get user

POST  /posts                          Create post (returns pre-signed URL for media)
POST  /posts/{post_id}/confirm        Activate post after S3 upload
GET   /posts/{post_id}                Get post details
GET   /posts/{post_id}/media-url      Get pre-signed GET URL for post media

GET   /hashtags/{tag}/count           Count of posts for hashtag (cached)
GET   /hashtags/{tag}/posts           Top 100 most-recent posts (cached)

GET   /notifications/{user_id}        List notifications (?unread_only&limit)
POST  /notifications/{user_id}/read   Mark notifications as read
```

---

## Running

```bash
cd hashtag-service
docker compose up --build
```

Docs available at http://localhost:8000/docs

### Quick smoke test

```bash
# 1. Create a user
USER=$(curl -s -X POST http://localhost:8000/users \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","email":"alice@example.com"}')
USER_ID=$(echo $USER | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 2a. Text-only post (immediately active)
curl -s -X POST http://localhost:8000/posts \
  -H 'Content-Type: application/json' \
  -d "{\"user_id\":\"$USER_ID\",\"caption\":\"Hello #python and #fastapi!\"}"

# 2b. Media post — get pre-signed URL
POST=$(curl -s -X POST http://localhost:8000/posts \
  -H 'Content-Type: application/json' \
  -d "{\"user_id\":\"$USER_ID\",\"caption\":\"My photo #travel\",\"media_filename\":\"photo.jpg\",\"media_content_type\":\"image/jpeg\"}")
POST_ID=$(echo $POST | python3 -c "import sys,json; print(json.load(sys.stdin)['post_id'])")
UPLOAD_URL=$(echo $POST | python3 -c "import sys,json; print(json.load(sys.stdin)['upload_url'])")

# 2c. Upload directly to S3 (pre-signed PUT)
curl -s -X PUT "$UPLOAD_URL" -H 'Content-Type: image/jpeg' --data-binary @photo.jpg

# 2d. Confirm the post
curl -s -X POST http://localhost:8000/posts/$POST_ID/confirm

# 3. Check hashtag count and top posts (wait ~1s for consumer)
sleep 1
curl -s http://localhost:8000/hashtags/python/count
curl -s http://localhost:8000/hashtags/python/posts

# 4. Check notifications
curl -s http://localhost:8000/notifications/$USER_ID
```
