import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Photo, PhotoStatus, User


def create_user(db: Session, email: str, username: str) -> User:
    user = User(email=email, username=username)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user(db: Session, user_id: uuid.UUID) -> User | None:
    return db.get(User, user_id)


def create_photo(
    db: Session,
    *,
    photo_id: uuid.UUID,
    user_id: uuid.UUID,
    filename: str,
    s3_key: str,
    is_private: bool,
) -> Photo:
    photo = Photo(
        id=photo_id,
        user_id=user_id,
        filename=filename,
        s3_key=s3_key,
        is_private=is_private,
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)
    return photo


def get_photo(db: Session, photo_id: uuid.UUID) -> Photo | None:
    return db.get(Photo, photo_id)


def set_status(db: Session, photo: Photo, status: PhotoStatus) -> Photo:
    photo.status = status
    photo.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(photo)
    return photo


def set_processed(db: Session, photo: Photo, processed_key: str) -> Photo:
    photo.processed_s3_key = processed_key
    photo.status = PhotoStatus.ready
    photo.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(photo)
    return photo


def list_user_photos(db: Session, user_id: uuid.UUID) -> list[Photo]:
    return db.query(Photo).filter(Photo.user_id == user_id).order_by(Photo.created_at.desc()).all()
