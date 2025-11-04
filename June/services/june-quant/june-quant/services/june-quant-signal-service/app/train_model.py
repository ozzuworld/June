import os
import numpy as np
import joblib

from sklearn.linear_model import Ridge
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import mean_squared_error


def generate_synthetic_prices(n: int = 1000, start: float = 60000.0):
    """
    Simple random walk price series for PoC.
    Replace this with real OHLCV loading later.
    """
    rng = np.random.default_rng(123)
    prices = [start]
    for _ in range(n - 1):
        # small random return around 0
        ret = rng.normal(0.0, 0.001)
        prices.append(prices[-1] * (1 + ret))
    return np.array(prices)


def build_dataset(prices: np.ndarray, horizon: int = 1):
    """
    Build a tiny dataset:
    - features: last return, repeated 10 times
    - target: next-step return
    """
    returns = prices[1:] / prices[:-1] - 1.0

    X = []
    y = []
    for t in range(len(returns) - horizon):
        r = returns[t]
        # feature vector of length 10 (simple, like orchestrator)
        feat = [r] * 10
        X.append(feat)
        y.append(returns[t + horizon])

    X = np.array(X)
    y = np.array(y)
    return X, y


def train_and_save_model():
    prices = generate_synthetic_prices()
    X, y = build_dataset(prices, horizon=1)

    print(f"Dataset shape: X={X.shape}, y={y.shape}")

    # Simple time-series CV just to make sure model isn't totally broken
    tscv = TimeSeriesSplit(n_splits=5)
    rmses = []
    for fold, (train_idx, test_idx) in enumerate(tscv.split(X), start=1):
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]

        model = Ridge(alpha=1.0)
        model.fit(X_train, y_train)
        preds = model.predict(X_test)

        # Older sklearn doesn't support squared=False, so we compute RMSE manually
        mse = mean_squared_error(y_test, preds)
        rmse = np.sqrt(mse)
        rmses.append(rmse)
        print(f"Fold {fold} RMSE: {rmse:.6f}")

    print(f"Avg RMSE: {np.mean(rmses):.6f}")

    # Train on full data
    final_model = Ridge(alpha=1.0)
    final_model.fit(X, y)

    # Save model in the same directory as this file: app/model.pkl
    base_dir = os.path.dirname(__file__)
    model_path = os.path.join(base_dir, "model.pkl")
    joblib.dump(final_model, model_path)
    print(f"Saved trained model to: {model_path}")


if __name__ == "__main__":
    train_and_save_model()
