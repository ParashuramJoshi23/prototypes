# Container image for the sse-logs prototype (Flask + Server-Sent Events).
# Built by the homelab onboarding flow and run against no backing stores —
# this demo is fully self-contained (logs are written to an emptyDir volume).
#
# Local dev is unchanged: `python app.py` still runs the Flask dev server on
# :5050. This image runs gunicorn on :8000 for the cluster.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
# gunicorn is a container-only dependency (prod WSGI server); the prototype's
# requirements.txt stays flask+faker so standalone local dev is untouched.
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

EXPOSE 8000

# gthread worker class + `--timeout 0`: an SSE response holds its worker thread
# for the entire life of the stream, so the default 30s worker timeout would
# kill long-lived log streams. Disable it and give each worker a thread pool.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", \
     "--workers", "2", "--worker-class", "gthread", "--threads", "16", \
     "--timeout", "0", "app:app"]
