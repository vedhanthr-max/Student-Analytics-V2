"""Payment helpers for the temporary direct UPI flow."""

from urllib.parse import urlencode


def build_upi_link(upi_id, payee_name, amount, note="Exam Fee Payment"):
    """Build a UPI payment intent using a server-controlled amount."""
    if not upi_id:
        raise ValueError("UPI ID is required")
    amount = float(amount)
    if amount <= 0:
        raise ValueError("Payment amount must be greater than zero")
    return "upi://pay?" + urlencode({
        "pa": upi_id,
        "pn": payee_name or "",
        "am": f"{amount:.2f}",
        "cu": "INR",
        "tn": note,
    })
