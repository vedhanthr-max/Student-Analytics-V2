"""Machine learning prediction and recommendation helpers."""

import os

import joblib
import pandas as pd

from config import MODEL_PATH, SCALER_PATH

PREDICTION_FEATURE_COLUMNS = [
    "Study_Hours",
    "Attendance",
    "Assignment_Marks",
    "Internal_Marks",
]

_model = None
_scaler = None


def _load_models():
    """Lazy-load ML artifacts so the app can start before training."""
    global _model, _scaler

    if _model is None:
        if not os.path.exists(MODEL_PATH) or not os.path.exists(SCALER_PATH):
            raise FileNotFoundError(
                "Model files not found. Run train_model.py first."
            )
        _model = joblib.load(MODEL_PATH)
        _scaler = joblib.load(SCALER_PATH)

    return _model, _scaler


def get_cluster_label_and_recommendation(cluster_id):
    """Map KMeans cluster id to a performance label and recommendation."""
    if cluster_id == 0:
        return "Excellent", "Keep up the great work."
    if cluster_id == 1:
        return "Need Improvement", "Meet your mentor and improve your study plan."
    if cluster_id == 2:
        return "Average", "Increase study hours and attendance."
    raise ValueError(f"Invalid prediction cluster: {cluster_id}")


def predict_student_performance(student):
    """
    Predict performance cluster for a student record.

    Returns:
        tuple: (level, recommendation)

    Raises:
        ValueError: when student data is invalid or incomplete.
        FileNotFoundError: when model files are missing.
    """
    model, scaler = _load_models()

    try:
        data = pd.DataFrame(
            [{
                "Study_Hours": student["study_hours"],
                "Attendance": student["attendance"],
                "Assignment_Marks": student["assignment_marks"],
                "Internal_Marks": student["internal_marks"],
            }],
            columns=PREDICTION_FEATURE_COLUMNS,
        ).astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError("Student prediction data is invalid") from exc

    if data.isna().any().any():
        raise ValueError("Student prediction data is incomplete")

    scaled_data = scaler.transform(data)
    cluster = int(model.predict(scaled_data)[0])
    return get_cluster_label_and_recommendation(cluster)
