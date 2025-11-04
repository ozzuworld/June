import os
import joblib
from .stub_model import StubRegressionModel


def load_model():
    """
    Try to load a trained model from disk.

    - Path is taken from env JUNE_QUANT_MODEL_PATH, default 'app/model.pkl'
    - If anything fails, we fall back to StubRegressionModel.

    The loaded object must implement .predict(X).
    """
    default_path = os.path.join(os.path.dirname(__file__), "model.pkl")
    model_path = os.getenv("JUNE_QUANT_MODEL_PATH", default_path)

    try:
        if os.path.exists(model_path):
            print(f"[model_loader] Loading model from: {model_path}")
            model = joblib.load(model_path)

            if not hasattr(model, "predict"):
                raise TypeError("Loaded object has no .predict() method")

            print("[model_loader] Successfully loaded trained model.")
            return model
        else:
            print(f"[model_loader] No model file found at {model_path}, using stub.")
    except Exception as e:
        print(f"[model_loader] Failed to load model ({e}), using stub.")

    # Fallback: stub model (still deterministic)
    print("[model_loader] Using StubRegressionModel as fallback.")
    return StubRegressionModel(n_features=10)
