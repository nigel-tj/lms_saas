"""Redis-backed rate limiting decorator for whitelisted API methods.

Usage:
    from lms_saas.utils.rate_limit import rate_limit

    @frappe.whitelist()
    @rate_limit(max_calls=5, window_seconds=60)
    def submit_loan_application(...):
        ...

Stores call counts in Redis with key ``lms_rl:{user}:{method}`` and TTL.
Returns 429 Too Many Requests with a friendly message on limit hit.
"""

from __future__ import annotations

import functools

import frappe


def rate_limit(max_calls: int = 10, window_seconds: int = 60):
    """Decorator: limit ``max_calls`` per ``window_seconds`` per user per method.

    Uses Redis (via frappe.cache) for atomic increment + TTL. Falls open
    (allows the call) if Redis is unavailable so a cache outage cannot block
    business operations.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user = frappe.session.user
            if user in ("Administrator", "Guest"):
                return fn(*args, **kwargs)

            method_key = f"lms_rl:{user}:{fn.__module__}.{fn.__name__}"
            try:
                current = frappe.cache().hincrby(method_key, "count", 1)
                if current == 1:
                    # First call in window — set expiry
                    frappe.cache().expire(method_key, window_seconds)
                if current > max_calls:
                    frappe.throw(
                        f"Too many requests. Please wait and try again in a moment. "
                        f"Limit: {max_calls} per {window_seconds}s.",
                        frappe.TooManyRequestsError,
                    )
            except frappe.TooManyRequestsError:
                raise
            except Exception:
                # Redis unavailable — fail open
                pass

            return fn(*args, **kwargs)

        return wrapper

    return decorator