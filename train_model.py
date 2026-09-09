import joblib
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from config import MODEL_PATH, SCALER_PATH

# Load Dataset
data = pd.read_csv("dataset/students.csv")

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
kmeans = KMeans(n_clusters=3, random_state=42)
kmeans.fit(X_scaled)

# Save
joblib.dump(kmeans, MODEL_PATH)
joblib.dump(scaler, SCALER_PATH)

print("Model Trained Successfully")
