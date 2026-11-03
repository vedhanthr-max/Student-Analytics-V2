"""Generate clearly marked synthetic student data for development."""

import csv
import random
from pathlib import Path


OUTPUT_PATH = Path(__file__).resolve().parents[1] / "dataset" / "synthetic_students.csv"


def generate_students(count=120):
    random.seed(42)
    rows = []
    for index in range(1, count + 1):
        rows.append({
            "Student_Name": f"Synthetic Student {index:03d}",
            "Study_Hours": round(random.uniform(1, 10), 1),
            "Attendance": random.randint(50, 100),
            "Assignment_Marks": random.randint(40, 100),
            "Internal_Marks": random.randint(40, 100),
            "source": "synthetic",
        })
    return rows


def main():
    rows = generate_students()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} synthetic rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
