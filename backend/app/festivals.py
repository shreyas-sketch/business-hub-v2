"""
Indian festivals and occasions for the content calendar (Oct 2026 – Dec 2027). Lunar dates follow published Indian
panchang calendars; Eid dates depend on the moon and can move by a day. The admin can extend this list in code each year.
"""
from datetime import date

FESTIVALS: list[tuple[str, str]] = [
    # 2026
    ("2026-10-02", "Gandhi Jayanti"), ("2026-10-11", "Navratri begins"), ("2026-10-20", "Dussehra"), ("2026-10-29", "Karwa Chauth"),
    ("2026-11-06", "Dhanteras"), ("2026-11-08", "Diwali"), ("2026-11-10", "Govardhan Puja and Gujarati New Year"),
    ("2026-11-11", "Bhai Dooj"), ("2026-11-14", "Children's Day"), ("2026-11-15", "Chhath Puja"), ("2026-11-24", "Guru Nanak Jayanti"),
    ("2026-12-25", "Christmas"), ("2026-12-31", "New Year's Eve"),
    # 2027
    ("2027-01-01", "New Year"), ("2027-01-13", "Lohri"), ("2027-01-14", "Makar Sankranti"), ("2027-01-15", "Pongal"),
    ("2027-01-26", "Republic Day"), ("2027-02-11", "Vasant Panchami"), ("2027-03-06", "Maha Shivaratri"),
    ("2027-03-08", "Women's Day"), ("2027-03-10", "Eid al-Fitr (moon dependent)"), ("2027-03-22", "Holi"),
    ("2027-04-01", "New financial year"), ("2027-04-07", "Ugadi and Gudi Padwa"), ("2027-04-14", "Baisakhi and Ambedkar Jayanti"),
    ("2027-04-15", "Ram Navami"), ("2027-04-19", "Mahavir Jayanti"), ("2027-05-09", "Akshaya Tritiya and Mother's Day"),
    ("2027-05-17", "Eid al-Adha (moon dependent)"), ("2027-05-20", "Buddha Purnima"), ("2027-06-20", "Father's Day"),
    ("2027-06-21", "International Yoga Day"), ("2027-07-01", "Doctors' Day and CA Day"), ("2027-08-01", "Friendship Day"),
    ("2027-08-15", "Independence Day"), ("2027-08-17", "Raksha Bandhan"), ("2027-08-25", "Janmashtami"),
    ("2027-09-04", "Ganesh Chaturthi"), ("2027-09-05", "Teachers' Day"), ("2027-09-12", "Onam"), ("2027-09-15", "Engineers' Day"),
    ("2027-09-30", "Navratri begins"), ("2027-10-02", "Gandhi Jayanti"), ("2027-10-09", "Dussehra"), ("2027-10-18", "Karwa Chauth"),
    ("2027-10-27", "Dhanteras"), ("2027-10-28", "Diwali"), ("2027-10-31", "Bhai Dooj"), ("2027-11-04", "Chhath Puja"),
    ("2027-11-14", "Children's Day and Guru Nanak Jayanti"), ("2027-12-25", "Christmas"), ("2027-12-31", "New Year's Eve"),
]


def in_month(year: int, month: int) -> list[dict]:
    prefix = f"{year:04d}-{month:02d}-"
    return [{"date": d, "name": n} for d, n in FESTIVALS if d.startswith(prefix)]


def upcoming(after: date, n: int = 5) -> list[dict]:
    return [{"date": d, "name": nm} for d, nm in FESTIVALS if d >= after.isoformat()][:n]
