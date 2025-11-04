import numpy as np
from fastapi import FastAPI

from .models import FeatureVector, SignalResponse
from .logic import decide_action
from .model_loader import load_model

app = FastAPI(title="june-quant-signal-service", version="0.1.0")

# Try to load a trained model; fall back to stub if not available
model = load_model()


@app.get("/health")
def health():
    return {"status": "ok", "service": "june-quant-signal-service"}


@app.post("/signal", response_model=SignalResponse)
def generate_signal(payload: FeatureVector):
    # Convert features (list[float]) into 2D array shape (1, n_features)
    X = np.array(payload.features, dtype=float).reshape(1, -1)

    # Predict expected return using whatever model is loaded (Ridge, stub, etc.)
    predicted = float(model.predict(X)[0])

    # Simple confidence proxy = |predicted_return|
    confidence = abs(predicted)

    # Decide LONG / SHORT / FLAT + risk fraction
    action, risk_fraction = decide_action(predicted)

    return SignalResponse(
        action=action,
        expected_return=predicted,
        confidence=confidence,
        risk_fraction=risk_fraction,
    )
