import unittest
from research.eth_basefee_feas_clo100 import activations

class T(unittest.TestCase):
    def test_two_day_spike_activates_once(self):
        f = [10]*35 + [40, 40, 40, 40] + [10]*20
        self.assertEqual(activations(f), [36])

    def test_single_spike_ignored(self):
        self.assertEqual(activations([10]*35 + [40] + [10]*10), [])

if __name__ == "__main__":
    unittest.main()
