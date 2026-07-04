import unittest

from lms_saas.utils.calculations import (
    asset_classification,
    ecl_stage,
    expected_credit_loss,
    par_bucket,
    principal_outstanding,
    remaining_payable,
)


class TestPrincipalOutstanding(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(principal_outstanding(10000, 2000, 0), 8000)

    def test_with_writeoff(self):
        self.assertEqual(principal_outstanding(10000, 2000, 1000), 7000)

    def test_never_negative(self):
        self.assertEqual(principal_outstanding(10000, 12000, 0), 0)

    def test_total_payment_not_subtracted(self):
        # Regression: interest-inclusive total_payment must not drive outstanding.
        self.assertEqual(principal_outstanding(22500, 0, 0), 22500)


class TestRemainingPayable(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(remaining_payable(10711.32, 0), 10711.32)

    def test_partial_paid(self):
        self.assertEqual(remaining_payable(10000, 2500), 7500)

    def test_never_negative(self):
        self.assertEqual(remaining_payable(10000, 11000), 0)


class TestAssetClassification(unittest.TestCase):
    def test_current(self):
        self.assertIsNone(asset_classification(0))
        self.assertIsNone(asset_classification(30))

    def test_watchlist(self):
        self.assertEqual(asset_classification(31), "Sub-Standard/Watchlist")
        self.assertEqual(asset_classification(90), "Sub-Standard/Watchlist")

    def test_npa(self):
        self.assertEqual(asset_classification(91), "Non-Performing Asset (NPA)")
        self.assertEqual(asset_classification(151), "Non-Performing Asset (NPA)")


class TestParBucket(unittest.TestCase):
    def test_buckets(self):
        self.assertEqual(par_bucket(0), "0 - Current")
        self.assertEqual(par_bucket(15), "1-30 Days")
        self.assertEqual(par_bucket(45), "31-60 Days")
        self.assertEqual(par_bucket(75), "61-90 Days")
        self.assertEqual(par_bucket(120), "90+ Days")


class TestECL(unittest.TestCase):
    def test_stages(self):
        self.assertEqual(ecl_stage(10), 1)
        self.assertEqual(ecl_stage(60), 2)
        self.assertEqual(ecl_stage(120), 3)

    def test_provision_amounts(self):
        self.assertAlmostEqual(expected_credit_loss(10000, 10), 100.0)   # stage 1: 1%
        self.assertAlmostEqual(expected_credit_loss(10000, 60), 1000.0)  # stage 2: 10%
        self.assertAlmostEqual(expected_credit_loss(10000, 120), 5000.0)  # stage 3: 50%


if __name__ == "__main__":
    unittest.main()
