def parse_status(page_text, title):
    low = page_text.lower()
    if title.lower() not in low:
        return ("absent", "")
    # "too long" first so it surfaces as the actionable reason when both it and
    # the generic "processing abandoned" notice are present.
    for phrase in ("too long", "processing abandoned"):
        if phrase in low:
            return ("failed", phrase)
    for phrase in ("processing", "checking"):
        if phrase in low:
            return ("processing", "")
    return ("present", "")
