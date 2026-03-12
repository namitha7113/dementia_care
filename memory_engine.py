def retrieve_from_memory(user_input, memory):
    """
    Deterministic memory retrieval for all natural question phrasings.
    Returns a string answer if found in memory, or None if no match.
    Never invents answers — only returns data actually stored in memory.
    """

    user_lower = user_input.lower()
    
    # -------- QUESTION VS NARRATIVE FILTER --------
    # Only proceed if it looks like a question
    question_indicators = ["who", "what", "where", "when", "name"]
    is_question = "?" in user_input or any(word in user_lower for word in question_indicators)
    
    # Explicitly skip if it starts with narrative markers (e.g., "I remember...")
    narrative_markers = ["i remember", "i went", "i saw", "i met", "i visited", "i was"]
    is_narrative = any(marker in user_lower for marker in narrative_markers)
    
    if not is_question or is_narrative:
        return None

    # -------- PATIENT NAME --------
    name_triggers = ["what is my name", "what's my name", "who am i", "my name", "tell me my name"]
    if any(t in user_lower for t in name_triggers):
        name = memory.get("patient_name")
        if name:
            return f"Your name is {name}."
        return "I'm not sure about your name right now."

    # -------- LOCATION --------
    location_triggers = ["where do i live", "where am i", "where i live", "my address",
                         "what city", "what place", "where is my home", "my location",
                         "live", "living"]
    if any(t in user_lower for t in location_triggers):
        location = memory.get("personal_info", {}).get("location")
        if location:
            return f"You live in {location}."
        return "I'm not sure where you live right now."

    # -------- MEDICATION --------
    med_triggers = ["medicine", "medication", "tablet", "pill", "drug", "prescription",
                    "when do i take", "what do i take"]
    if any(t in user_lower for t in med_triggers):
        med_time = memory.get("medical_info", {}).get("medication_time")
        if med_time:
            return f"You take your medicine at {med_time}."
        return "I don't have your medication details right now."

    # -------- FAMILY MEMBERS — all natural phrasings --------
    family = memory.get("family", {})

    # Direct relation lookup: "who is my father", "what is my daughter's name", "tell me about my son"
    relation_triggers = [
        "who is my", "what is my", "what's my", "tell me about my", "do i have a",
        "my", "name of my"
    ]
    import re as _re

    # Sort longest relation first so 'grandfather' is checked before 'father'
    sorted_family = sorted(family.items(), key=lambda x: len(x[0]), reverse=True)

    for relation, name_val in sorted_family:
        # Use word-boundary match, but allow optional 's' or 's at the end
        # so "father's name" or "fathers name" matches "father"
        if _re.search(r'\b' + _re.escape(relation) + r"(?:'s|s)?\b", user_lower):
            return f"Your {relation} is {name_val}."

        # Reverse: user says the name, asking who it is
        if name_val and _re.search(r'\b' + _re.escape(name_val.lower()) + r"(?:'s|s)?\b", user_lower):
            return f"{name_val} is your {relation}."

    # -------- PREFERENCES --------
    preferences = memory.get("preferences", {})
    pref_triggers = ["favorite", "favourite", "like", "enjoy", "love", "prefer"]
    is_pref_question = any(t in user_lower for t in pref_triggers)

    for category, value in preferences.items():
        if category in user_lower:
            return f"Your favorite {category} is {value}."
        if is_pref_question and value.lower() in user_lower:
            return f"Yes, {value} is your favorite {category}."

    # If asked about preferences in general but no specific match
    if is_pref_question and preferences:
        parts = [f"{cat}: {val}" for cat, val in preferences.items()]
        return "Here are your preferences — " + ", ".join(parts) + "."

    # -------- EVENTS --------
    events = memory.get("events", [])
    event_triggers = ["event", "happen", "visit", "went", "met", "saw", "trip", "vacation"]
    if any(t in user_lower for t in event_triggers) and events:
        return "Here are some things I remember: " + "; ".join(events[-3:]) + "."

    # -------- PERSONAL INFO (generic key-value store) --------
    personal_info = memory.get("personal_info", {})
    for key, value in personal_info.items():
        if key in user_lower:
            return f"{key.capitalize()}: {value}."

    # -------- PHOTOS — summarise who is in photos --------
    photos = memory.get("photos", [])
    photo_triggers = ["photo", "picture", "image", "photograph", "who is in"]
    if any(t in user_lower for t in photo_triggers) and photos:
        # Build a deduplicated list of people in photos
        people = list({f"{p.get('person')} ({p.get('relationship')})"
                       for p in photos if p.get("person")})
        if people:
            return "The photos contain: " + ", ".join(people) + "."

    return None
