"""Machine learning prediction and recommendation helpers."""

import os

import joblib
import pandas as pd

from config import BASE_DIR, MODEL_PATH, SCALER_PATH

PREDICTION_FEATURE_COLUMNS = [
    "Study_Hours",
    "Attendance",
    "Assignment_Marks",
    "Internal_Marks",
]

_model = None
_scaler = None
_label_map = None


def _load_models():
    """Lazy-load ML artifacts so the app can start before training."""
    global _model, _scaler, _label_map

    if _model is None:
        label_map_path = os.path.join(BASE_DIR, "models", "label_map.pkl")
        if (
            not os.path.exists(MODEL_PATH)
            or not os.path.exists(SCALER_PATH)
            or not os.path.exists(label_map_path)
        ):
            raise FileNotFoundError("Run train_model.py first.")
        _model = joblib.load(MODEL_PATH)
        _scaler = joblib.load(SCALER_PATH)
        _label_map = joblib.load(label_map_path)

    return _model, _scaler, _label_map


RECOMMENDATIONS = {
    "Excellent": "Keep up the great work.",
    "Average": "Increase study hours and attendance.",
    "Need Improvement": "Meet your mentor and improve your study plan.",
}


def predict_student_performance(student):
    """
    Predict performance cluster for a student record.

    Returns:
        tuple: (level, recommendation)

    Raises:
        ValueError: when student data is invalid or incomplete.
        FileNotFoundError: when model files are missing.
    """
    model, scaler, label_map = _load_models()

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
    try:
        level = label_map[cluster]
        recommendation = RECOMMENDATIONS[level]
    except KeyError as exc:
        raise ValueError(f"Invalid prediction cluster: {cluster}") from exc
    return level, recommendation
