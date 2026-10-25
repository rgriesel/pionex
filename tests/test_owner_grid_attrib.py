import unittest

from pionex_lab.research.owner_grid_attrib import dsign


class DSign(unittest.TestCase):
    def test_signs(self):
        self.assertEqual((dsign("long"), dsign("short"), dsign(""), dsign(None)), (1, -1, 0, 0))


if __name__ == "__main__":
    unittest.main()
