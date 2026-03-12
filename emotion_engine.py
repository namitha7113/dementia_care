def detect_emotion(user_input):
    user_lower = user_input.lower()

    if any(word in user_lower for word in ["confused", "forget", "don't remember"]):
        return "confusion"

    if any(word in user_lower for word in ["scared", "afraid", "anxious", "nervous"]):
        return "anxiety"

    if any(word in user_lower for word in ["sad", "lonely", "upset"]):
        return "sadness"

    return "neutral"


def update_emotional_state(emotion, session_state):
    """
    Tracks emotional streaks and calculates intensity.
    Does NOT interfere with memory logic.
    """

    if "emotion_streak" not in session_state:
        session_state.emotion_streak = 0

    if "last_emotion" not in session_state:
        session_state.last_emotion = None

    if "emotion_intensity" not in session_state:
        session_state.emotion_intensity = "low"

    # If same emotion repeats → increase streak
    if emotion == session_state.last_emotion and emotion != "neutral":
        session_state.emotion_streak += 1
    else:
        session_state.emotion_streak = 1 if emotion != "neutral" else 0

    session_state.last_emotion = emotion

    # Adaptive intensity scaling
    if session_state.emotion_streak >= 3:
        session_state.emotion_intensity = "high"
    elif session_state.emotion_streak == 2:
        session_state.emotion_intensity = "medium"
    else:
        session_state.emotion_intensity = "low"

    return session_state.emotion_intensity