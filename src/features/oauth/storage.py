"""Firestore によるトークンの永続化。"""

from google.cloud import firestore

from config import FIRESTORE_COLLECTION, PROJECT_ID

_db: firestore.Client | None = None


def get_db() -> firestore.Client:
    global _db
    if _db is None:
        _db = firestore.Client(project=PROJECT_ID)
    return _db


def save_tokens(user_id: str, tokens: dict) -> None:
    get_db().collection(FIRESTORE_COLLECTION).document(user_id).set(tokens)


def load_tokens(user_id: str) -> dict | None:
    doc = get_db().collection(FIRESTORE_COLLECTION).document(user_id).get()
    return doc.to_dict() if doc.exists else None


def delete_tokens(user_id: str) -> None:
    get_db().collection(FIRESTORE_COLLECTION).document(user_id).delete()
