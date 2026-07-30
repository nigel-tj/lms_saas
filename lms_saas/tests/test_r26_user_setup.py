"""R26 — LMS User Setup adversarial-review regression tests.

The detailed tests live next to their DocType controller at
``lms_saas/lms_saas/lms_saas/doctype/lms_user_setup/test_lms_user_setup.py``.
This file re-imports them under the ``lms_saas.tests.*`` namespace so the
canonical ``run_lms_tests.py`` discovery picks them up.

DRY: the underlying tests live in ONE place. Add new LMS User Setup
tests to the ``TestLMSUserSetupR26`` class in the doctype-level test file
— this module re-imports them automatically.
"""

# The full package path resolves via `lms_saas.lms_saas.doctype...`.
# The inner `lms_saas` package lives at apps/lms_saas/lms_saas/lms_saas,
# so the dotted import goes one level deeper than the outer package name.
from lms_saas.lms_saas.doctype.lms_user_setup.test_lms_user_setup import (
	TestLMSUserSetup,
	TestLMSUserSetupR26,
)

__all__ = ["TestLMSUserSetup", "TestLMSUserSetupR26"]
