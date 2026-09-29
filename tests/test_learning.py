import tempfile
import unittest
from pathlib import Path

from analog_layout import optimize
from benchmark_circuits import FAMILIES, make_circuit
from placement_learning import MovePolicy, features


class LearningTests(unittest.TestCase):
    def test_all_generated_families_are_valid(self):
        for family in FAMILIES:
            for seed in range(10):
                spec = make_circuit(family, seed)
                self.assertTrue(spec["synthetic"])

    def test_frozen_policy_roundtrip_and_constraint_preservation(self):
        spec = make_circuit(FAMILIES[0], 0)
        observed = []
        optimize(spec, 300, policy="uniform", observations=observed)
        rows = [features(spec, c, p, a) for c, p, a, _ in observed]
        model = MovePolicy.fit(rows, [r for _, _, _, r in observed], {})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.json"
            model.save(path)
            loaded = MovePolicy.load(path)
        before = loaded.weights.copy()
        result = optimize(spec, 300, seed=9, policy="learned", learned_policy=loaded)
        self.assertFalse(result["violations"])
        self.assertTrue((before == loaded.weights).all())
        self.assertEqual(model.predict(spec, 100, 0.5), loaded.predict(spec, 100, 0.5))

    def test_missing_model_rejected(self):
        with self.assertRaises(ValueError):
            optimize(make_circuit(FAMILIES[0], 0), policy="learned")
