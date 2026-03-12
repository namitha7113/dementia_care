import json
import re

UNCERTAINTY_WORDS = ["maybe", "i think", "probably", "not sure", "might"]


def contains_uncertainty(text):
    text = text.lower()
    return any(word in text for word in UNCERTAINTY_WORDS)

def save_memory(memory):
    """
    Merge-write: reads existing file first and merges all fields
    so no stored data (patient_name, family, photos, etc.) is lost.
    """
    import os
    path = "memory_store.json"

    # Load existing data
    existing = {}
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                existing = json.load(f)
        except:
            existing = {}

    # Deep merge: existing data is the base, incoming memory updates on top
    merged = existing.copy()
    for key, value in memory.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            # Merge dicts (e.g. family, personal_info, medical_info, preferences)
            merged[key] = {**merged[key], **value}
        elif isinstance(value, list) and key == "photos":
            # Photos: use incoming list (already deduplicated by add_photo_metadata)
            merged[key] = value
        elif isinstance(value, list) and key == "events":
            # Events: merge and deduplicate
            existing_events = merged.get("events", [])
            merged[key] = existing_events + [e for e in value if e not in existing_events]
        else:
            merged[key] = value

    with open(path, "w") as f:
        json.dump(merged, f, indent=4)


def update_memory(user_input, memory):
    """
    Dynamically extracts structured factual information
    and updates JSON memory deterministically.
    """

    text = user_input.strip()
    lower_text = text.lower()

    if contains_uncertainty(lower_text):
        return None  # Do not store uncertain statements

    updated = False

    # -------- PATIENT NAME --------
    name_match = re.match(r"my name is (.+)", lower_text)
    if name_match:
        memory["patient_name"] = name_match.group(1).title()
        updated = True

    # -------- LOCATION --------
    location_match = re.match(r"i live in (.+)", lower_text)
    if location_match:
        memory.setdefault("personal_info", {})
        memory["personal_info"]["location"] = location_match.group(1).title()
        updated = True

    # -------- MEDICATION TIME --------
    med_match = re.match(r"i take medicine at (.+)", lower_text)
    if med_match:
        memory.setdefault("medical_info", {})
        memory["medical_info"]["medication_time"] = med_match.group(1)
        updated = True

    # -------- DYNAMIC FAMILY RELATIONSHIP --------
    relation_match = re.match(r"my (\w+) is (.+)", lower_text)
    if relation_match:
        relationship = relation_match.group(1)
        value = relation_match.group(2).title()

        memory.setdefault("family", {})
        memory["family"][relationship] = value
        updated = True

    # -------- FAMILY NAME FORMAT --------
    relation_name_match = re.match(r"my (\w+)'?s name is (.+)", lower_text)
    if relation_name_match:
        relationship = relation_name_match.group(1)
        value = relation_name_match.group(2).title()

        memory.setdefault("family", {})
        memory["family"][relationship] = value
        updated = True

    # -------- PREFERENCES --------
    pref_match = re.match(r"my favorite (\w+) is (.+)", lower_text)
    if pref_match:
        category = pref_match.group(1)
        value = pref_match.group(2).title()

        memory.setdefault("preferences", {})
        memory["preferences"][category] = value
        updated = True

    # -------- EVENT MEMORY --------
    event_match = re.match(r"i (went|met|visited|saw) (.+)", lower_text)
    if event_match:
        memory.setdefault("events", [])

        event_text = text  # store original sentence
        memory["events"].append(event_text)

        updated = True

    # -------- GENERIC FACT MEMORY --------
    # Guard: skip if it looks like a question (starts with who/what/where/when/how etc.)
    question_starters = ["who", "what", "where", "when", "how", "which", "do i", "am i", "is my"]
    is_question = any(lower_text.startswith(q) for q in question_starters) or lower_text.endswith("?")

    fact_match = re.match(r"(.+) is (.+)", lower_text)
    if fact_match and not relation_match and not is_question:
        key = fact_match.group(1).strip()
        value = fact_match.group(2).strip().title()

        # Skip single-word or question-word keys that are clearly not facts
        skip_keys = {"who", "what", "where", "when", "how", "he", "she", "it", "that", "this"}
        if key and key not in skip_keys and len(key.split()) <= 4:
            memory.setdefault("personal_info", {})
            memory["personal_info"][key] = value
            updated = True

    if updated:
        save_memory(memory)
        return memory

    return None