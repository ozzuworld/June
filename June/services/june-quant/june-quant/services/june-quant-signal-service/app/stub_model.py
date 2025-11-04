import numpy as np


class StubRegressionModel:
    """
    Very simple deterministic stub model for june-quant PoC.

    - Computes a dot product between features and a fixed weight vector.
    - Applies a scaling factor so outputs are in a range that actually
      triggers LONG/SHORT decisions with the 0.35% target logic.

    This is ONLY for wiring/testing the infra. Later we'll replace this
    with a real trained regression model (e.g. scikit-learn + joblib).
    """

    def __init__(self, n_features: int = 10, seed: int = 42):
        rng = np.random.default_rng(seed)
        # Small random weights
        self.weights = rng.normal(loc=0.0, scale=0.1, size=n_features)
        self.bias = 0.0
        # Bigger scale so the PoC actually generates LONG/SHORT signals
        # (instead of always staying FLAT).
        self.scale = 10.0

    def predict(self, X):
        X = np.asarray(X)

        # Ensure shape (n_samples, n_features)
        if X.ndim == 1:
            X = X.reshape(1, -1)

        n_features = self.weights.shape[0]

        # If feature size mismatch, pad with zeros or truncate
        if X.shape[1] < n_features:
            pad_width = n_features - X.shape[1]
            X = np.pad(X, ((0, 0), (0, pad_width)), mode="constant")
        elif X.shape[1] > n_features:
            X = X[:, :n_features]

        raw = X @ self.weights + self.bias
        return self.scale * raw
