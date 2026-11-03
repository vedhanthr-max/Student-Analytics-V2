"""Backward-compatible recommendation helper.

Prefer services.prediction.get_cluster_label_and_recommendation for new code.
"""

from services.prediction import get_cluster_label_and_recommendation


def get_recommendation(cluster):
    """Return recommendation text for a KMeans cluster id."""
    _, recommendation = get_cluster_label_and_recommendation(cluster)
    return recommendation
