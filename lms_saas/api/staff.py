"""Staff onboarding hooks.

Routes LMS desk users onto the locked-down `LMS Staff` module profile so new or
edited staff automatically get the focused Loan Management sidebar, with zero
per-user setup. The actual logic lives in `lms_saas.install` (single source of
truth for the lockdown); this module is the thin doc_event entry point.
"""

from lms_saas.install import apply_lms_module_profile as _apply_lms_module_profile


def apply_lms_module_profile(doc, method=None):
    _apply_lms_module_profile(doc, method=method)
