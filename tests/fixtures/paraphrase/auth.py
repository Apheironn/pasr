"""Authentication helpers."""


def authenticate_the_request_using_a_bearer_token(request):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    return _lookup_principal(header.removeprefix("Bearer "))


def invalidate_every_session_for_a_compromised_user(user_id):
    return _sessions.delete_where(user_id=user_id)


def rotate_the_signing_key_on_a_fixed_schedule(keyring, now):
    if now - keyring.created_at > keyring.max_age:
        keyring.rotate()
    return keyring


def _lookup_principal(token):
    return _sessions.get(token)
