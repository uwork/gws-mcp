"""itsdangerous による state トークンの生成・検証。"""

from itsdangerous import URLSafeTimedSerializer

from config import STATE_SECRET_KEY

_serializer = URLSafeTimedSerializer(STATE_SECRET_KEY)


def create_state(data: dict) -> str:
    return _serializer.dumps(data)


def verify_state(token: str, max_age: int = 600) -> dict | None:
    try:
        return _serializer.loads(token, max_age=max_age)
    except Exception:
        return None
