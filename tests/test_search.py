import unittest

import numpy as np

from mirror_search import expected_improvement


class SearchTests(unittest.TestCase):
    def test_surrogate_interpolates_measured_scores(self):
        x = np.array([[0, 0, 0], [1, 1, 1], [0, 1, 0], [1, 0, 1]], dtype=float)
        scores = np.array([1, 4, 2, 3], dtype=float)
        acquisition, predicted, uncertainty = expected_improvement(x, x, scores)
        np.testing.assert_allclose(predicted, scores, atol=1e-3)
        self.assertTrue(np.all(acquisition >= 0))
        self.assertTrue(np.all(uncertainty > 0))

    def test_unobserved_points_retain_uncertainty(self):
        x = np.array([[0, 0, 0], [0.2, 0, 0]], dtype=float)
        _, _, near = expected_improvement(x, x, [1, 2])
        _, _, far = expected_improvement(np.array([[1, 1, 1]]), x, [1, 2])
        self.assertGreater(float(far[0]), float(near.max()))
