from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema():
    if not DATABASE_URL.startswith("sqlite"):
        return
    with engine.connect() as conn:
        cols = conn.execute(text("PRAGMA table_info(video_processing)")).fetchall()
        existing = {row[1] for row in cols}
        if "action_items" not in existing:
            conn.execute(
                text("ALTER TABLE video_processing ADD COLUMN action_items TEXT DEFAULT ''")
            )
        conn.commit()
