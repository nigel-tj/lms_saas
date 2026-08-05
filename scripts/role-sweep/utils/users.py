"""Canonical list of pilot-sweep test users.

This mirrors apps/lms_saas/lms_saas/setup/live_repair.py's TEST_USERS table.
If that table changes, this must change too — the sweep asserts each user's
landing page, so any new persona needs both roles here + a per-role test.
"""
from __future__ import annotations

USERS = {
    "borrower": {
        "email": "borrower@example.com",
        "password": "Borrower@123",
        "persona": "Borrower",
        "landing": "/lms",
        "roles": ["Customer"],
    },
    "officer": {
        "email": "officer@kesari.africa",
        "password": "Officer@123",
        "persona": "Loan Officer",
        "landing": "/lms/officer",
        "roles": ["LMS Portal Staff"],
    },
    "field": {
        "email": "field@kesari.africa",
        "password": "Field@123",
        "persona": "Loan Officer",
        "landing": "/lms/officer",
        "roles": ["LMS Portal Staff"],
        "read_only": True,
    },
    "manager": {
        "email": "manager@kesari.africa",
        "password": "Manager@123",
        "persona": "Branch Manager",
        "landing": "/lms/manager",
        "roles": ["LMS Portal Staff"],
    },
    "supervisor": {
        "email": "supervisor@kesari.africa",
        "password": "Supervisor@123",
        "persona": "Branch Manager",
        "landing": "/lms/manager",
        "roles": ["LMS Portal Staff"],
        "read_only": True,
    },
    "admin": {
        "email": "admin@kesari.africa",
        "password": "Admin@123",
        "persona": "Branch Manager",
        "landing": "/desk",
        "roles": ["LMS Portal Staff", "System Manager", "Administrator"],
    },
    "collector": {
        "email": "collector@kesari.africa",
        "password": "Collector@123",
        "persona": "Collector",
        "landing": "/lms/collect",
        "roles": ["LMS Portal Staff"],
    },
    "senior": {
        "email": "senior.collector@kesari.africa",
        "password": "Senior@123",
        "persona": "Collector",
        "landing": "/lms/collect",
        "roles": ["LMS Portal Staff"],
        "read_only": True,
    },
}

# Primary vs read-only test ordering used by sweep.py
PRIMARY = ["borrower", "officer", "manager", "collector", "admin"]
READ_ONLY = ["field", "supervisor", "senior"]


def get(key: str) -> dict:
    if key not in USERS:
        raise KeyError(f"unknown sweep user: {key!r}; known: {sorted(USERS)}")
    return USERS[key]
