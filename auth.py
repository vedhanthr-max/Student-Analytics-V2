"""Backward-compatible authentication exports.

The application uses the helpers in ``utils.auth``. This module re-exports
those helpers for older integrations that import ``auth`` directly.
"""

from utils.auth import login_required, roles_required, student_identity

__all__ = ["login_required", "roles_required", "student_identity"]
