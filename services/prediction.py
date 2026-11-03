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
LABEL_MAP_PATH = os.path.join(BASE_DIR, "models", "label_map.pkl")

RECOMMENDATIONS = {
    "Excellent": "Keep up the great work.",
    "Average": "Increase study hours and attendance.",
    "Need Improvement": "Meet your mentor and improve your study plan.",
}

_model = None
_scaler = None
_label_map = None


def _load_models():
    """Lazy-load ML artifacts so the app can start before training."""
    global _model, _scaler, _label_map

    if _model is None:
        if not all(
            os.path.exists(path)
            for path in (MODEL_PATH, SCALER_PATH, LABEL_MAP_PATH)
        ):
            raise FileNotFoundError("Run train_model.py first.")
        _model = joblib.load(MODEL_PATH)
        _scaler = joblib.load(SCALER_PATH)
        _label_map = joblib.load(LABEL_MAP_PATH)

    return _model, _scaler, _label_map


def _student_data(student):
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
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Student prediction data is invalid") from exc

    if data.isna().any().any():
        raise ValueError("Student prediction data is incomplete")
    return data


def explain_cluster(student):
    """Return original-unit feature gaps from the predicted cluster center."""
    model, scaler, _ = _load_models()
    data = _student_data(student)
    scaled_data = scaler.transform(data)
    cluster = int(model.predict(scaled_data)[0])
    center = scaler.inverse_transform(model.cluster_centers_)[cluster]
    values = data.iloc[0].to_numpy(dtype=float)
    return {
        feature: float(value - center[index])
        for index, (feature, value) in enumerate(
            zip(PREDICTION_FEATURE_COLUMNS, values)
        )
    }


def _specific_recommendation(label, gaps):
    recommendation = RECOMMENDATIONS[label]
    feature, gap = min(gaps.items(), key=lambda item: item[1])
    if gap >= 0:
        return recommendation

    feature_name = feature.replace("_", " ")
    return (
        f"{recommendation} {feature_name.title()} is "
        f"{abs(gap):.1f} points below the group average."
    )


def predict_student_performance(student):
    """
    Predict performance cluster for a student record.

    Returns:
        tuple: (level, recommendation)
    """
    model, scaler, label_map = _load_models()
    data = _student_data(student)
    scaled_data = scaler.transform(data)
    cluster = int(model.predict(scaled_data)[0])

    try:
        level = label_map[cluster]
        gaps = explain_cluster(student)
        recommendation = _specific_recommendation(level, gaps)
    except KeyError as exc:
        raise ValueError(f"Invalid prediction cluster: {cluster}") from exc
    return level, recommendation


# A supervised pass-probability model can be added when historical ``passed``
# values are present; the current schema has no such column, so it is skipped.
