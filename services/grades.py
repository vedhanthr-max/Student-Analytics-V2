"""Grade and result calculation helpers."""


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
