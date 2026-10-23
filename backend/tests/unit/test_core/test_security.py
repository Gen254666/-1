from steel_core.security import hash_password, verify_password


def test_hash_and_verify_password() -> None:
    hashed = hash_password("secret-123")

    assert hashed != "secret-123"
    assert verify_password(hashed, "secret-123") is True
    assert verify_password(hashed, "wrong-password") is False


def test_verify_password_rejects_invalid_hash() -> None:
    assert verify_password("not-a-hash", "secret-123") is False
