"""The QR code maker (jcc/qr.py), against values from the QR standard's worked examples."""
import unittest

from jcc import qr


class TestQr(unittest.TestCase):
    def test_reed_solomon_matches_the_standard_example(self):
        data = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17]     # "HELLO WORLD", version 1-M
        self.assertEqual(qr.rs_remainder(data, 10), [196, 35, 39, 119, 235, 215, 231, 226, 93, 23])

    def test_format_and_version_bits(self):
        self.assertEqual(format(qr.format_bits(0), "015b"), "101010000010010")
        self.assertEqual(format(qr.format_bits(5), "015b"), "100000011001110")
        self.assertEqual(format(qr.version_bits(7), "018b"), "000111110010010100")

    def test_a_pairing_link_fits_and_the_finders_are_in_place(self):
        grid = qr.matrix("https://jarvis-abcd2345.someone.workers.dev/#p=0123456789abcdef.K7QM2XHD")
        n = len(grid)
        self.assertEqual((n - 17) % 4, 0)
        for x0, y0 in ((0, 0), (n - 7, 0), (0, n - 7)):
            self.assertTrue(all(grid[y0][x0 + i] and grid[y0 + 6][x0 + i] for i in range(7)))
            self.assertFalse(grid[y0 + 1][x0 + 1])
        self.assertTrue(grid[n - 8][8], "the dark module")

    def test_too_long_is_refused_and_svg_is_escaped(self):
        with self.assertRaises(ValueError):
            qr.matrix("x" * 400)
        self.assertIn('aria-label="a &lt;b &quot;x&quot;"', qr.svg("hi", 'a <b "x"'))


if __name__ == "__main__":
    unittest.main()
