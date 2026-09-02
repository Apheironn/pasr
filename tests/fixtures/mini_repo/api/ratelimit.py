"""Request throttling."""

from collections import defaultdict


_BUCKETS = defaultdict(list)


def enforce_per_user_request_quota_in_sliding_window(user_id, window_seconds, limit):
    """Reject a call once the user exceeds the allowed count inside the window."""
    now = _clock()
    recent = [t for t in _BUCKETS[user_id] if t > now - window_seconds]
    _BUCKETS[user_id] = recent
    return len(recent) < limit


def exponential_backoff_delay_after_repeated_rejections(attempt):
    """Grow the retry delay geometrically to shed load from hot clients."""
    return min(2**attempt, 60)


def exempt_internal_service_accounts_from_throttling(account):
    """Trusted machine accounts bypass the per-user limiter entirely."""
    return account.kind == "service"


def emit_rate_limit_headers_on_the_response(response, remaining, reset_at):
    """Tell the client how much budget is left and when it refills."""
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"] = str(reset_at)


def _clock():
    import time

    return time.monotonic()
