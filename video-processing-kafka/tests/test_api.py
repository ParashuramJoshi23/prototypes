import os
import tempfile

from fastapi.testclient import TestClient


def test_upload_and_status(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        upload_dir = os.path.join(tmpdir, "uploads")

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setenv("UPLOAD_DIR", upload_dir)
        monkeypatch.setenv("KAFKA_BROKER", "localhost:9092")

        from app.main import app  # imported after env set
        import app.main as main_module
        monkeypatch.setattr(main_module, "send_event", lambda *args, **kwargs: None)

        client = TestClient(app)
        response = client.post(
            "/upload",
            files={"file": ("sample.mp4", b"fake", "video/mp4")},
        )
        assert response.status_code == 200
        data = response.json()
        assert "video_id" in data

        status = client.get(f"/status/{data['video_id']}")
        assert status.status_code == 200
        body = status.json()
        assert body["status"] == "queued"
        assert body["file_path"]
