import re

def normalize_sa_mobile(value):
  

    if not value:
        return None

    cleaned = re.sub(r"\D", "", str(value))

    # -------------------------
    # Format: 0821234567 (local)
    # -------------------------
    if cleaned.startswith("0") and len(cleaned) == 10:
        return "+27" + cleaned[1:]

    # -------------------------
    # Format: 27821234567 (international without +)
    # -------------------------
    if cleaned.startswith("27") and len(cleaned) == 11:
        return "+" + cleaned

    # -------------------------
    # Format: +27821234567 (after cleaning still 278...)
    # -------------------------
    if cleaned.startswith("27") and len(cleaned) == 12:
        return "+" + cleaned

    return None