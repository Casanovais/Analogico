import copy
import json
import unittest
from pathlib import Path

from analog_layout import optimize, validate, violations, wire_cost


class PlacementTests(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads(Path("examples/differential_pair.json").read_text())

    def test_known_initial_cost(self):
        self.assertEqual(wire_cost(self.spec, self.spec["devices"]), 136.0)

    def test_optimizer_preserves_constraints_and_is_reproducible(self):
        a = optimize(self.spec, steps=1000, seed=17)
        self.assertEqual(a, optimize(self.spec, steps=1000, seed=17))
        self.assertFalse(a["violations"])
        self.assertLess(a["best_cost"], a["initial_cost"])
        self.assertEqual(self.spec["devices"][0]["x"], 5)

    def test_spacing_boundary_and_symmetry(self):
        devices = copy.deepcopy(self.spec["devices"])
        devices[0]["x"] = -1
        self.assertTrue(any("outside" in v for v in violations(self.spec, devices)))
        self.assertTrue(any("symmetry" in v for v in violations(self.spec, devices)))
        devices = copy.deepcopy(self.spec["devices"])
        devices[4].update(x=5, y=5)
        self.assertTrue(any("overlap" in v for v in violations(self.spec, devices)))

    def test_bad_net_rejected(self):
        self.spec["nets"][0]["devices"].append("missing")
        with self.assertRaises(ValueError):
            validate(self.spec)

    def test_uniform_baseline(self):
        result = optimize(self.spec, steps=1000, seed=17, policy="uniform")
        self.assertFalse(result["violations"])
        self.assertLessEqual(result["best_cost"], result["initial_cost"])


if __name__ == "__main__":
    unittest.main()
