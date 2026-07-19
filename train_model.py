import pandas as pd
import joblib

from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

# Load Dataset
data = pd.read_csv("dataset/students.csv")

# Features
X = data[
[
"Study_Hours",
"Attendance",
"Assignment_Marks",
"Internal_Marks"
]
]

# Scale Data
scaler = StandardScaler()

X_scaled = scaler.fit_transform(X)

# KMeans

kmeans = KMeans(
n_clusters=3,
random_state=42
)

kmeans.fit(X_scaled)

# Save

joblib.dump(kmeans,"models/kmeans_model.pkl")

joblib.dump(scaler,"models/scaler.pkl")

print("Model Trained Successfully")