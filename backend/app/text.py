"""Small text helpers shared by the AI drafts and WhatsApp messages."""

TITLES = {"mr", "mrs", "ms", "miss", "dr", "shri", "shree", "smt", "sri", "kumari", "prof", "er", "adv", "ca"}


def greeting_name(name: str) -> str:
    """How to address someone in a message: 'Mrs. Kulkarni' stays whole, 'Neha Joshi' becomes 'Neha'."""
    parts = (name or "").split()
    if not parts:
        return ""
    if parts[0].rstrip(".").lower() in TITLES:
        return " ".join(parts[:2]) if len(parts) > 1 else ""
    return parts[0]
