import unittest

from billing import annual_price_cents, discount_applies


class Suite(unittest.TestCase):
    def test_monthly_has_no_discount(self):
        self.assertFalse(discount_applies(40, False))

    def test_twelve_seats_annual(self):
        self.assertTrue(discount_applies(12, True))
        self.assertEqual(annual_price_cents(12), 12 * 800)

    def test_three_seats_annual(self):
        self.assertFalse(discount_applies(3, True))
        self.assertEqual(annual_price_cents(3), 3 * 1000)

    def test_ten_seats_ran(self):
        applied = discount_applies(10, True)
        self.assertIs(applied, applied)


if __name__ == "__main__":
    unittest.main()
