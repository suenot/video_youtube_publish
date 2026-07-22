import json
from pathlib import Path


def cap_tags(tags, budget=480):
    out, used = [], 0
    for t in tags:
        add = len(t) + (1 if out else 0)
        if used + add > budget:
            break
        out.append(t)
        used += add
    return out


# YouTube rejects angle brackets in the title and description. The details form
# refuses to save and shows the error on hover over the disabled Save button, so
# an automated run just sees a save that never lands. Fullwidth forms are
# accepted and read the same.
ANGLE_BRACKETS = {"<": "＜", ">": "＞"}


def strip_angle_brackets(text):
    """PURE: replace < and > with their fullwidth equivalents."""
    for bad, good in ANGLE_BRACKETS.items():
        text = text.replace(bad, good)
    return text


def load_metadata(metadata_path, title, description, tags_csv):
    meta = {"title": "", "description": "", "tags": []}
    if metadata_path:
        p = Path(metadata_path).expanduser()
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            meta["title"] = (data.get("title") or "").strip()
            meta["description"] = data.get("description") or ""
            meta["tags"] = [t for t in (data.get("tags") or []) if t]
    if title:
        meta["title"] = title
    if description:
        meta["description"] = description
    if tags_csv:
        meta["tags"] = [t.strip() for t in tags_csv.split(",") if t.strip()]
    meta["title"] = strip_angle_brackets(meta["title"])[:100]
    meta["description"] = strip_angle_brackets(meta["description"])
    meta["tags"] = cap_tags(meta["tags"])
    return meta
