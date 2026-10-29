import unittest
from billing import discount_applies, annual_price_cents


class KillTest(unittest.TestCase):
    def test_boundary_kills(self):
        self.assertTrue(discount_applies(10, True))
        self.assertEqual(annual_price_cents(10), 10 * 800)


if __name__ == '__main__':
    unittest.main()
