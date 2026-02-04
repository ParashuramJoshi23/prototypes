# Video Processing Pipeline (FastAPI + Celery + Kafka)

A minimal local system that accepts a video upload and runs async tasks:
1. Generate transcript
2. Add summary
3. Add bulletpoints
4. Deepgram translation (stub)
5. Create thumbnail (stub)
6. Send completion message

Each step updates the database and emits a Kafka event. Logging includes a trace id so you can follow a job across services.

## Run locally (Docker)

```bash
docker compose up --build
```

Open `http://localhost:8000` to upload a video.

Check status:

```bash
curl http://localhost:8000/status/<video_id>
```

## Dead-letter handling
Failed tasks are retried with exponential backoff. If a task still fails after retries, a message is published to the `video.dlq` Kafka topic.

## Tests
```bash
pytest
```

## Services
- `app`: FastAPI upload + status API
- `consumer`: Kafka consumer that starts the Celery chain per upload
- `worker`: Celery worker executing tasks

## Notes
- Thumbnail creation uses `ffmpeg` inside the Docker image. Replace the command with your desired thumbnail logic if needed.
- If you ran earlier versions, delete `./data/app.db` to recreate schema with the new `file_path` column.
- SQLite data and uploads are stored in `./data`.



## Screenshot

<img width="871" height="845" alt="Screenshot 2026-02-04 at 5 26 17 PM" src="https://github.com/user-attachments/assets/35273ee3-4a55-497f-b156-9b0a89665b5f" />
