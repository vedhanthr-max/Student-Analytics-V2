import os

import joblib
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from config import BASE_DIR, MODEL_PATH, SCALER_PATH

LABEL_MAP_PATH = os.path.join(BASE_DIR, "models", "label_map.pkl")

data = pd.read_csv(os.path.join(BASE_DIR, "dataset", "students.csv"))

# Features
X = data[
    [
        "Study_Hours",
        "Attendance",
        "Assignment_Marks",
        "Internal_Marks",
    ]
]

# Scale Data
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

# KMeans
kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
kmeans.fit(X_scaled)

strength = kmeans.cluster_centers_.mean(axis=1)
ordered_clusters = sorted(
    range(len(strength)),
    key=lambda cluster_id: strength[cluster_id],
    reverse=True,
)
labels = ["Excellent", "Average", "Need Improvement"]
label_map = {
    cluster_id: labels[position]
    for position, cluster_id in enumerate(ordered_clusters)
}

joblib.dump(kmeans, MODEL_PATH)
joblib.dump(scaler, SCALER_PATH)
joblib.dump(label_map, LABEL_MAP_PATH)

print("Model Trained Successfully")
