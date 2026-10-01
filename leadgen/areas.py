"""Map a lead's address to a Mumbai launch area (first match wins)."""

AREAS = {
    "Andheri": ["andheri", "marol", "chakala", "jogeshwari", "sakinaka", "versova", "seepz"],
    "BKC / Bandra": ["bkc", "bandra", "khar", "santacruz", "kalina"],
    "Lower Parel / Worli": ["lower parel", "parel", "worli", "prabhadevi", "mahalaxmi", "elphinstone", "dadar"],
    "Powai": ["powai", "hiranandani", "chandivali"],
    "Goregaon": ["goregaon"],
    "Malad": ["malad", "kandivali"],
    "Vikhroli": ["vikhroli", "kanjurmarg", "bhandup"],
    "Ghatkopar": ["ghatkopar", "vidyavihar", "kurla", "sion"],
    "South Mumbai": ["nariman", "fort", "colaba", "churchgate", "ballard", "kala ghoda", "cuffe parade"],
    "Chembur": ["chembur", "deonar", "mankhurd"],
    "Borivali": ["borivali", "dahisar"],
    "Navi Mumbai / Thane": ["navi mumbai", "sanpada", "vashi", "belapur", "thane", "airoli", "turbhe", "juinagar"],
}


def area_of(address):
    text = (address or "").lower()
    for area, keywords in AREAS.items():
        if any(k in text for k in keywords):
            return area
    return "Other"