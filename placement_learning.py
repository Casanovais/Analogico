"""Portable supervised move-reward model; no evaluation-time weight updates."""
import json
from pathlib import Path

import numpy as np

MOVE_SIZES = [1, 2, 4, 8]
FEATURE_VERSION = 1


def features(spec, cost, progress, action):
    width, height = spec["boundary"]
    n = len(spec["devices"])
    area = sum(d["width"] * d["height"] for d in spec["devices"])
    size = MOVE_SIZES[action] / max(width, height)
    wire = cost / max(1, (width + height) * len(spec["nets"]))
    occupancy = area / (width * height)
    # Quadratic interactions allow move preference to vary with search phase,
    # circuit density and remaining wire cost. Units are normalized.
    return [1, progress, progress**2, size, size**2, wire, occupancy,
            n / 20, len(spec["nets"]) / n, size * progress,
            size * wire, size * occupancy, size * n / 20,
            size**2 * progress, size * progress**2]


class MovePolicy:
    def __init__(self, mean, scale, weights, metadata=None):
        self.mean = np.asarray(mean)
        self.scale = np.asarray(scale)
        self.weights = np.asarray(weights)
        self.metadata = metadata or {}

    @classmethod
    def fit(cls, rows, rewards, metadata):
        x = np.asarray(rows, dtype=float)
        y = np.asarray(rewards, dtype=float)
        mean = x.mean(axis=0)
        scale = x.std(axis=0)
        mean[0], scale[0] = 0, 1
        scale[scale < 1e-8] = 1
        z = (x - mean) / scale
        regularization = np.eye(x.shape[1]) * 10
        regularization[0, 0] = 0
        weights = np.linalg.solve(z.T @ z + regularization, z.T @ y)
        model = cls(mean, scale, weights, metadata)
        model.metadata["training_mse"] = float(np.mean((z @ weights - y)**2))
        return model

    def predict(self, spec, cost, progress):
        x = np.asarray([features(spec, cost, progress, a) for a in range(4)])
        return (((x - self.mean) / self.scale) @ self.weights).tolist()

    def save(self, path):
        Path(path).write_text(json.dumps({"feature_version": FEATURE_VERSION,
                                         "mean": self.mean.tolist(), "scale": self.scale.tolist(),
                                         "weights": self.weights.tolist(), "metadata": self.metadata}, indent=2) + "\n")

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text())
        if data["feature_version"] != FEATURE_VERSION:
            raise ValueError("Incompatible policy feature version")
        return cls(data["mean"], data["scale"], data["weights"], data["metadata"])
