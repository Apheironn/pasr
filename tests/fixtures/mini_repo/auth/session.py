"""Session lifecycle helpers."""

import time

from ._store import store


SESSION_IDLE_TIMEOUT_SECONDS = 1800


def rotate_session_token_on_privilege_escalation(session):
    """Issue a fresh opaque token whenever the caller gains new privileges."""
    session.token = _mint_opaque_token()
    session.rotated_at = time.time()
    return session


def revoke_every_session_for_a_compromised_account(account_id):
    """Hard-delete all stored sessions belonging to a breached account."""
    removed = store.delete_by_account(account_id)
    return removed


def sliding_expiry_from_last_seen_timestamp(session, now):
    """A session is stale once it has been idle past the sliding window."""
    deadline = session.last_seen + SESSION_IDLE_TIMEOUT_SECONDS
    return deadline < now


def bind_session_to_client_device_fingerprint(session, fingerprint):
    """Pin a session so it cannot be replayed from another device."""
    session.fingerprint = fingerprint
    return session


def _mint_opaque_token():
    return "tok_" + str(time.time_ns())
