"""features/oauth/state.py の単体テスト。"""

import time
from unittest.mock import patch

from features.oauth.state import create_state, verify_state


def test_roundtrip_preserves_all_fields():
    data = {"user_id": "abc123", "code_challenge": "xyz", "nested": {"k": 1}}
    token = create_state(data)
    assert verify_state(token) == data


def test_verify_invalid_token_returns_none():
    assert verify_state("not-a-valid-token") is None


def test_verify_empty_string_returns_none():
    assert verify_state("") is None


def test_verify_tampered_token_returns_none():
    token = create_state({"user_id": "abc"})
    # 末尾数文字を書き換える
    tampered = token[:-6] + "XXXXXX"
    assert verify_state(tampered) is None


def test_verify_expired_token_returns_none():
    """max_age=600 で 601 秒前に発行されたトークンは無効になる。"""
    past = time.time() - 601
    with patch("time.time", return_value=past):
        token = create_state({"user_id": "abc"})
    assert verify_state(token) is None


def test_verify_custom_max_age_is_respected():
    token = create_state({"user_id": "fresh"})
    # max_age=3600 では有効
    assert verify_state(token, max_age=3600) is not None


def test_verify_max_age_negative_always_expires():
    token = create_state({"user_id": "abc"})
    assert verify_state(token, max_age=-1) is None
