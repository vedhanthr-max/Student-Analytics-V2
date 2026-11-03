"""Train and save the student performance clustering model."""

import json
import os
from datetime import datetime, timezone

import joblib
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from config import BASE_DIR, MODEL_PATH, SCALER_PATH
from utils.database import get_connection

FEATURE_COLUMNS = [
    "Study_Hours",
    "Attendance",
    "Assignment_Marks",
    "Internal_Marks",
]
LABEL_MAP_PATH = os.path.join(BASE_DIR, "models", "label_map.pkl")
MODEL_META_PATH = os.path.join(BASE_DIR, "models", "model_meta.json")


def _load_training_data():
    """Load non-zero database features or fall back to the CSV dataset."""
    with get_connection() as conn:
        database_data = pd.read_sql_query(
            """
            SELECT study_hours AS Study_Hours,
                   attendance AS Attendance,
                   assignment_marks AS Assignment_Marks,
                   internal_marks AS Internal_Marks
            FROM students
            WHERE COALESCE(study_hours, 0) != 0
              AND COALESCE(attendance, 0) != 0
              AND COALESCE(assignment_marks, 0) != 0
              AND COALESCE(internal_marks, 0) != 0
            """,
            conn,
        )

    if len(database_data) >= 10:
        print(f"Training source: SQLite students table ({len(database_data)} rows)")
        return database_data[FEATURE_COLUMNS], "sqlite"

    csv_path = os.path.join(BASE_DIR, "dataset", "students.csv")
    csv_data = pd.read_csv(csv_path)
    print(f"Training source: {csv_path} ({len(csv_data)} rows)")
    return csv_data[FEATURE_COLUMNS], "dataset/students.csv"


def _build_label_map(model):
    """Map clusters to labels by descending center strength."""
    strength = model.cluster_centers_.mean(axis=1)
    ordered_clusters = sorted(
        range(len(strength)),
        key=lambda cluster_id: strength[cluster_id],
        reverse=True,
    )
    cluster_count = len(ordered_clusters)
    label_map = {}

    for position, cluster_id in enumerate(ordered_clusters):
        if cluster_count == 3:
            label = ["Excellent", "Average", "Need Improvement"][position]
        elif position < cluster_count / 3:
            label = "Excellent"
        elif position >= (cluster_count * 2) / 3:
            label = "Need Improvement"
        else:
            label = "Average"
        label_map[cluster_id] = label

    return label_map


def train():
    """Train the best clustering model and save its artifacts."""
    started_at = datetime.now(timezone.utc)
    data, source = _load_training_data()
    scaler = StandardScaler()
    scaled_data = scaler.fit_transform(data)

    best_model = None
    best_score = float("-inf")
    max_k = min(5, len(data) - 1)
    for k in range(2, max_k + 1):
        candidate = KMeans(n_clusters=k, random_state=42, n_init=10)
        candidate.fit(scaled_data)
        score = silhouette_score(scaled_data, candidate.labels_)
        if score > best_score:
            best_model = candidate
            best_score = score

    if best_model is None:
        raise ValueError("At least three training rows are required.")

    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump(best_model, MODEL_PATH)
    joblib.dump(scaler, SCALER_PATH)
    joblib.dump(_build_label_map(best_model), LABEL_MAP_PATH)

    metadata = {
        "k": best_model.n_clusters,
        "silhouette_score": best_score,
        "sample_count": len(data),
        "source": source,
        "training_time": (datetime.now(timezone.utc) - started_at).total_seconds(),
    }
    with open(MODEL_META_PATH, "w", encoding="utf-8") as file:
        json.dump(metadata, file, indent=2)

    print(
        f"Model trained: k={metadata['k']}, "
        f"silhouette={metadata['silhouette_score']:.4f}, "
        f"samples={metadata['sample_count']}"
    )
    return metadata


if __name__ == "__main__":
    train()
