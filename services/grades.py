"""Grade and result calculation helpers."""

INTERNAL_MARK_MIN = 0
INTERNAL_MARK_MAX = 40
EXTERNAL_MARK_MIN = 0
EXTERNAL_MARK_MAX = 60


def calculate_grade(total):
    """
    Calculate grade letter, grade point, and pass/fail result
    from a combined internal + external mark total.
    """
    if total >= 90:
        return "O", 10, "Pass"
    if total >= 80:
        return "A+", 9, "Pass"
    if total >= 70:
        return "A", 8, "Pass"
    if total >= 60:
        return "B+", 7, "Pass"
    if total >= 50:
        return "B", 6, "Pass"
    if total >= 45:
        return "C", 5, "Pass"
    return "RA", 0, "Fail"


def parse_marks(internal_value, external_value):
    """Parse and validate internal and external marks."""
    try:
        internal = float(internal_value)
        external = float(external_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Marks must be valid numbers.") from exc

    if not INTERNAL_MARK_MIN <= internal <= INTERNAL_MARK_MAX:
        raise ValueError("Internal mark must be between 0 and 40.")
    if not EXTERNAL_MARK_MIN <= external <= EXTERNAL_MARK_MAX:
        raise ValueError("External mark must be between 0 and 60.")

    return internal, external


def compute_gpa(rows):
    """Compute weighted GPA from result rows."""
    total_points = sum(row["grade_point"] * row["credits"] for row in rows)
    total_credits = sum(row["credits"] for row in rows)
    return round(total_points / total_credits, 2) if total_credits else 0


def compute_summary(rows):
    """Compute aggregate result statistics."""
    total_credits = sum(row["credits"] for row in rows)
    total_marks = sum(row["total_mark"] for row in rows)
    pass_count = sum(row["result"] == "Pass" for row in rows)
    fail_count = len(rows) - pass_count
    average_marks = round(total_marks / len(rows), 2) if rows else 0

    return {
        "total_credits": total_credits,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "average_marks": average_marks,
        "gpa": compute_gpa(rows),
    }
