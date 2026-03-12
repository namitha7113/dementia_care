import streamlit as st
import json
import os
import random
from dotenv import load_dotenv
from gtts import gTTS
from huggingface_hub import InferenceClient

# --------- LAYER IMPORTS ----------
from memory_engine import retrieve_from_memory
from emotion_engine import detect_emotion, update_emotional_state
from memory_update_engine import update_memory

# --------- STABLE MEMORY FILE PATH FIX ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_PATH = os.path.join(BASE_DIR, "memory_store.json")


# ---------------- LOAD ENV ----------------

load_dotenv()
HF_API_KEY = os.getenv("HF_API_KEY")

if not HF_API_KEY:
    st.error("HF_API_KEY not found. Please check your .env file.")
    st.stop()

# ---------------- HUGGING FACE CLIENT ----------------

client = InferenceClient(
    model="HuggingFaceH4/zephyr-7b-beta",
    token=HF_API_KEY
)

# ---------------- SESSION STATE ----------------

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# -------- PHOTO RECALL SCORE STATE --------
if "photo_score" not in st.session_state:
    st.session_state.photo_score = {
        "correct": 0,
        "incorrect": 0,
        "unsure": 0
    }

# -------- ASKED QUIZ QUESTIONS TRACKER --------
if "asked_questions" not in st.session_state:
    st.session_state.asked_questions = set()

# ---------------- LOAD MEMORY ----------------

def load_memory():
    try:
        with open(MEMORY_PATH, "r") as f:
            return json.load(f)
    except:
        return {}

# ---------------- SAVE MEMORY ----------------

def save_memory(memory):
    with open(MEMORY_PATH, "w") as f:
        json.dump(memory, f, indent=4)

# ---------------- CLEAN MEMORY FOR LLM ----------------

def clean_memory_for_llm(memory):
    """
    Returns a copy of memory safe to send to the LLM:
    - Strips file_name from every photo entry so image filenames
      never appear in generated text (prevents hallucination).
    """
    import copy
    m = copy.deepcopy(memory)
    if "photos" in m:
        cleaned_photos = []
        for p in m["photos"]:
            cleaned_photos.append({
                "person": p.get("person", ""),
                "relationship": p.get("relationship", ""),
                "event": p.get("event", ""),
                "year": p.get("year", "")
            })
        m["photos"] = cleaned_photos
    return m

# ---------------- ADD PHOTO METADATA ----------------

def add_photo_metadata(file_name, person, relationship, event, year):

    print("Saving memory to:", MEMORY_PATH)

    if os.path.exists(MEMORY_PATH):
        with open(MEMORY_PATH, "r") as f:
            memory = json.load(f)
    else:
        memory = {}

    if "photos" not in memory:
        memory["photos"] = []

    photo_entry = {
        "file_name": file_name,
        "person": person,
        "relationship": relationship,
        "event": event,
        "year": year
    }

    # Remove any existing entry for this filename (deduplication)
    # so photos[-1] is always the true latest upload
    memory["photos"] = [
        p for p in memory["photos"]
        if p.get("file_name") != file_name
    ]

    # Append as the latest entry
    memory["photos"].append(photo_entry)

    with open(MEMORY_PATH, "w") as f:
        json.dump(memory, f, indent=4)

    print("Photo metadata saved:", photo_entry)

# ---------------- RESPONSE GENERATION ----------------

def generate_response(user_input):

    memory = load_memory()

    # Step 1: Try to update memory from what the user said
    updated_memory = update_memory(user_input, memory)
    if updated_memory:
        memory = updated_memory

    emotion = detect_emotion(user_input)
    intensity = update_emotional_state(emotion, st.session_state)

    user_lower = user_input.lower()

    # Step 2: Identify Factual Questions vs Narratives
    question_indicators = ["who", "what", "where", "when", "name"]
    is_question = "?" in user_input or any(word in user_lower for word in question_indicators)
    
    narrative_markers = ["i remember", "i went", "i saw", "i met", "i visited", "i was"]
    is_narrative = any(marker in user_lower for marker in narrative_markers)

    # Step 3: Trigger Deterministic memory lookup ONLY for factual questions
    if is_question and not is_narrative:
        memory_reply = retrieve_from_memory(user_input, memory)
        if memory_reply is not None:
            st.session_state.chat_history.append({"role": "user",      "content": user_input})
            st.session_state.chat_history.append({"role": "assistant", "content": memory_reply})
            return memory_reply

    # Step 4: Fallback for factual questions memory doesn't have
    factual_keywords = [
        "who", "what", "where", "when", "which", "how",
        "name", "daughter", "son", "mother", "father", "grandfather",
        "grandmother", "husband", "wife", "brother", "sister", "uncle",
        "aunt", "cousin", "friend",
        "live", "location", "address", "city", "place",
        "medication", "medicine", "pill", "tablet", "dose",
        "favorite", "favourite", "like", "prefer",
        "age", "birthday", "born", "old",
        "doctor", "hospital", "nurse", "caregiver",
        "tell me about", "do i have", "am i", "is my", "are my"
    ]
    is_likely_factual = any(kw in user_lower for kw in factual_keywords)

    if is_likely_factual and not is_narrative:
        no_info = "I don't have that information in your records right now. Please ask your caregiver to update your details."
        st.session_state.chat_history.append({"role": "user",      "content": user_input})
        st.session_state.chat_history.append({"role": "assistant", "content": no_info})
        return no_info

    # Step 5: Human-like Emotional / Conversational — Grounded in memory to prevent hallucination
    st.session_state.chat_history.append({"role": "user", "content": user_input})

    # Prepare context for LLM
    safe_memory = clean_memory_for_llm(memory)
    # Get last 2 messages for shorter context (faster/more stable)
    history_context = st.session_state.chat_history[-3:-1] if len(st.session_state.chat_history) > 1 else []

    try:
        # Construct a more natural, restrained friend persona
        system_msg = f"""You are Sam, a dear friend of {safe_memory.get('patient_name', 'Lakshmi')}. 
You are here to chat and listen. Talk like a real friend sitting nearby.

Natural Conversation Rules:
1. Don't dump everything you know. Only mention names (like Rohan or Vivek) or places (like Kochi) if {safe_memory.get('patient_name', 'Lakshmi')} mentions them first or if it's very relevant to her current mood.
2. For a simple "hello", just be warm and ask how she's doing today.
3. Be a good listener. If she's happy, share the joy. If she's sad, offer a kind word.
4. Keep it very brief—usually just 1 or 2 warm sentences.
5. NEVER sound like a computer. Be human.
"""
        messages = [{"role": "system", "content": system_msg}]
        messages.extend(history_context)
        messages.append({"role": "user", "content": user_input})

        response = client.chat_completion(
            messages=messages,
            max_tokens=80,
            temperature=0.7 # Back to a more stable temperature
        )

        reply = response.choices[0].message.content.strip()

        # Clip to 3 sentences max for a more human feel
        sentences = [s.strip() for s in reply.split(".") if s.strip()]
        reply = ". ".join(sentences[:3])
        if reply and not reply.endswith((".", "?", "!")):
            reply += "."

        st.session_state.chat_history.append({"role": "assistant", "content": reply})
        return reply

    except Exception as e:
        print(f"LLM Error: {e}") # Print error to terminal for debugging
        safe_reply = "I'm right here with you, Lakshmi. Take a deep breath — everything is going to be just fine."
        st.session_state.chat_history.append({"role": "assistant", "content": safe_reply})
        return safe_reply




# ---------------- CAREGIVER SUMMARY ----------------

def generate_caregiver_summary():

    confusion_count = 0
    anxiety_count = 0
    sadness_count = 0
    factual_failures = 0
    reassurance_count = 0


    for message in st.session_state.chat_history:

        if message["role"] == "user":

            text = message["content"].lower()

            if any(word in text for word in ["confused","forget","don't remember"]):
                confusion_count += 1

            if any(word in text for word in ["scared","afraid","anxious"]):
                anxiety_count += 1

            if any(word in text for word in ["sad","lonely","upset"]):
                sadness_count += 1


        if message["role"] == "assistant":

            text = message["content"].lower()

            if "i'm not sure about that right now" in text:
                factual_failures += 1

            if any(word in text for word in ["it's okay","you are safe","i'm here"]):
                reassurance_count += 1


    if anxiety_count > 0:
        emotional_state = "Signs of anxiety observed."

    elif sadness_count > 0:
        emotional_state = "Signs of sadness observed."

    elif confusion_count > 0:
        emotional_state = "Memory confusion episodes observed."

    else:
        emotional_state = "Emotional state remained stable."


    if confusion_count > 2:
        memory_status = "Repeated confusion patterns detected."

    elif confusion_count > 0:
        memory_status = "Mild memory confusion noted."

    else:
        memory_status = "No significant memory confusion detected."


    if factual_failures > 0:
        factual_status = f"{factual_failures} factual recall failures detected."

    else:
        factual_status = "No factual recall failures observed."


    if reassurance_count > 3:
        support_level = "Frequent reassurance provided."

    elif reassurance_count > 0:
        support_level = "Moderate reassurance provided."

    else:
        support_level = "Minimal reassurance required."


    correct = st.session_state.photo_score["correct"]
    incorrect = st.session_state.photo_score["incorrect"]
    unsure = st.session_state.photo_score["unsure"]

    total = correct + incorrect + unsure


    if total > 0:

        accuracy = round((correct / total) * 100)

        photo_summary = f"""
Photo Recall Analysis:
- Correct recalls: {correct}
- Incorrect recalls: {incorrect}
- Uncertain responses: {unsure}
- Accuracy: {accuracy}%
"""

    else:

        photo_summary = """
Photo Recall Analysis:
- No recall attempts recorded.
"""

    # -------- COGNITIVE QUIZ RESULTS --------
    quiz_results = st.session_state.get("quiz_results", [])

    if quiz_results:
        q_correct = sum(1 for r in quiz_results if r["correct"] is True)
        q_total   = len(quiz_results)
        q_pct     = round((q_correct / q_total) * 100) if q_total else 0

        quiz_lines = [
            f"Cognitive Quiz Results ({q_correct}/{q_total} correct, {q_pct}%):"
        ]
        for i, r in enumerate(quiz_results, 1):
            status = "✓ Correct" if r["correct"] is True else ("✗ Incorrect" if r["correct"] is False else "~ Attempted")
            quiz_lines.append(f"  Q{i}: {r['question']}")
            quiz_lines.append(f"       Patient answered : {r['user_answer']}")
            if r.get("expected"):
                quiz_lines.append(f"       Expected answer  : {r['expected']}")
            quiz_lines.append(f"       Result           : {status}")

        quiz_summary = "\n".join(quiz_lines)
    else:
        quiz_summary = "Cognitive Quiz:\n- No quiz attempted this session."

    return f"""
Caregiver Summary:

Emotional Analysis:
- {emotional_state}

Memory Analysis:
- {memory_status}
- {factual_status}

Support Assessment:
- {support_level}

{photo_summary}
{quiz_summary}
""".strip()



import hashlib

@st.cache_data
def speak(text):
    """
    Generates an audio file for the given text using gTTS.
    Uses caching to avoid redundant requests and handles connection errors.
    """
    if not text:
        return None

    # Create a unique filename for this text to avoid re-downloading
    file_hash = hashlib.md5(text.encode()).hexdigest()
    audio_dir = os.path.join(BASE_DIR, "audio_cache")
    os.makedirs(audio_dir, exist_ok=True)
    audio_path = os.path.join(audio_dir, f"speech_{file_hash}.mp3")

    # If already generated, return the path
    if os.path.exists(audio_path):
        return audio_path

    try:
        tts = gTTS(text)
        tts.save(audio_path)
        return audio_path
    except Exception as e:
        # Log error to console but don't crash the app
        print(f"gTTS Error: {e}")
        return None

# ---------------- LLM QUIZ GENERATOR ----------------

def generate_llm_quiz(memory):
    """
    Generates quiz Q&A pairs from memory.
    Returns a list of dicts: [{"question": ..., "answer": ...}, ...]
    - Strips file names before sending to the LLM.
    - Deduplicates against already-asked questions.
    """
    import re as _re
    import json as _json

    safe_memory = clean_memory_for_llm(memory)

    prompt = f"""
You are helping test memory recall for a dementia patient.

Using ONLY the information in the memory below, generate 10 simple recall question-and-answer pairs.

Rules:
- Do NOT invent any information not present in the memory.
- Use family members, patient name, preferences, events or location.
- Keep questions short and gentle.
- Do NOT mention any file names, image names, or technical identifiers.
- Return the result as a JSON array with objects: {{"question": "...", "answer": "..."}}
- The answer must be the concise expected answer (1-5 words).
- Output ONLY the JSON array, nothing else.

Memory:
{safe_memory}
"""

    response = client.chat_completion(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=500
    )

    raw_text = response.choices[0].message.content.strip()

    # Extract JSON array from the response (handle markdown fences)
    json_match = _re.search(r'\[.*\]', raw_text, _re.DOTALL)
    qa_pairs = []
    if json_match:
        try:
            qa_pairs = _json.loads(json_match.group())
        except Exception:
            qa_pairs = []

    # Fallback: if JSON parse failed, extract questions only
    if not qa_pairs:
        for line in raw_text.splitlines():
            line = line.strip()
            cleaned = _re.sub(r'^\d+[.)\s]+', '', line).strip()
            if cleaned and '?' in cleaned:
                qa_pairs.append({"question": cleaned, "answer": ""})

    # Filter already-asked questions
    new_pairs = [
        qa for qa in qa_pairs
        if qa.get("question", "") not in st.session_state.asked_questions
    ]

    if not new_pairs:
        st.session_state.asked_questions = set()
        new_pairs = qa_pairs

    selected = new_pairs[:5]

    for qa in selected:
        st.session_state.asked_questions.add(qa.get("question", ""))

    return selected

# ---------------- UI ----------------

st.title("🧠 Dementia AI Assistant")

st.markdown("Emotional Companion Mode")


from streamlit_mic_recorder import speech_to_text

st.markdown("💬 **Talk to the assistant (Voice or Text):**")

# Voice input widget
voice_input = speech_to_text(
    language='en',
    start_prompt="🎙️ Click to Speak",
    stop_prompt="🛑 Stop Recording",
    just_once=True,
    use_container_width=True,
    key='STT'
)

# Text fallback
user_input_text = st.text_input("Or type here:", key="chat_text_input")
send_pressed = st.button("Send Text")

final_input = None
if voice_input:
    final_input = voice_input
elif send_pressed and user_input_text:
    final_input = user_input_text

if final_input:
    with st.spinner("Assistant is thinking..."):
        generate_response(final_input)
    st.rerun()



for message in st.session_state.chat_history:

    if message["role"] == "user":

        st.write("You:", message["content"])

    else:

        st.write("Assistant:", message["content"])

        if message["content"]:
            audio_file = speak(message["content"])
            if audio_file:
                st.audio(audio_file)



st.divider()


if st.button("Generate Caregiver Summary"):

    summary = generate_caregiver_summary()

    st.subheader("Caregiver Summary")

    st.write(summary)



# ---------------- PHOTO UPLOAD ----------------

st.divider()
st.subheader("📷 Caregiver Photo Upload")

with st.form("photo_upload_form"):

    uploaded_file = st.file_uploader(
        "Upload a familiar photo",
        type=["jpg", "jpeg", "png"]
    )

    person_name = st.text_input("Person in photo:")
    relationship = st.text_input("Relationship to patient:")
    event = st.text_input("Event in photo:")
    year = st.text_input("Year (optional):")

    submit_photo = st.form_submit_button("Save Photo Metadata")


if submit_photo:

    if uploaded_file is None:
        st.warning("Please upload a photo.")

    elif person_name == "" or relationship == "":
        st.warning("Please enter person name and relationship.")

    else:

        # ensure photo folder exists
        os.makedirs("uploaded_photos", exist_ok=True)

        file_path = os.path.join("uploaded_photos", uploaded_file.name)

        # save image file
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        # -------- SAVE METADATA --------
        add_photo_metadata(
            file_name=uploaded_file.name,
            person=person_name,
            relationship=relationship,
            event=event,
            year=year
        )

        st.success("Photo and metadata saved successfully.")

        st.rerun()

# ---------------- PHOTO RECALL MODULE ----------------

st.divider()

st.subheader("🧠 Photo-Based Memory Recall")

memory = load_memory()

photos = memory.get("photos", [])


if photos:

    if st.button("Start Photo Recall"):

        st.session_state.current_photo = photos[-1]  # always use the latest uploaded photo

        st.session_state.recall_active = True


if "recall_active" in st.session_state and st.session_state.recall_active:

    photo = st.session_state.current_photo

    image_path = os.path.join("uploaded_photos", photo["file_name"])


    if os.path.exists(image_path):

        st.image(image_path, caption="Memory Recall Photo", use_container_width=True)


    st.write("Who is in this picture?")


    recall_answer = st.text_input("Patient Response:", key="recall_input")


    if st.button("Submit Recall Answer"):

        correct_person = photo["person"].lower()

        correct_relationship = photo["relationship"].lower()

        answer_lower = recall_answer.lower()


        if correct_person in answer_lower:

            response = f"Yes, that is {photo['person']}, your {photo['relationship']}."

            st.session_state.photo_score["correct"] += 1


        elif correct_relationship in answer_lower:

            response = f"Yes, that is your {photo['relationship']}, {photo['person']}."

            st.session_state.photo_score["correct"] += 1


        elif any(word in answer_lower for word in ["don't know","not sure","forget"]):

            response = f"That's okay. This is {photo['person']}, your {photo['relationship']}."

            st.session_state.photo_score["unsure"] += 1


        else:

            response = f"This is {photo['person']}, your {photo['relationship']}."

            st.session_state.photo_score["incorrect"] += 1


        st.write("Assistant:", response)

        audio_file = speak(response)
        if audio_file:
            st.audio(audio_file)

        st.session_state.recall_active = False

# ---------------- COGNITIVE QUIZ MODULE ----------------

# Session state for interactive quiz
if "quiz_questions" not in st.session_state:
    st.session_state.quiz_questions = []      # list of {question, answer}
if "quiz_index" not in st.session_state:
    st.session_state.quiz_index = 0           # which question we are on
if "quiz_results" not in st.session_state:
    st.session_state.quiz_results = []        # {question, user_answer, correct, expected}
if "quiz_active" not in st.session_state:
    st.session_state.quiz_active = False

st.divider()
st.subheader("🧠 Cognitive Quiz")

memory = load_memory()

# ---- START QUIZ ----
if not st.session_state.quiz_active:
    if st.button("Generate Cognitive Quiz"):
        with st.spinner("Generating quiz from memory..."):
            qa_list = generate_llm_quiz(memory)
        if qa_list:
            st.session_state.quiz_questions = qa_list
            st.session_state.quiz_index = 0
            st.session_state.quiz_results = []
            st.session_state.quiz_active = True
            st.rerun()
        else:
            st.warning("Could not generate questions. Please add more information to memory first.")

# ---- ACTIVE QUIZ: show one question at a time ----
if st.session_state.quiz_active:
    questions = st.session_state.quiz_questions
    idx = st.session_state.quiz_index
    total = len(questions)

    if idx < total:
        qa = questions[idx]
        question_text = qa.get("question", "")
        expected_answer = qa.get("answer", "").strip().lower()

        st.markdown(f"**Question {idx + 1} of {total}**")
        st.progress((idx) / total)
        st.markdown(f"### {question_text}")

        user_ans = st.text_input(
            "Your answer:",
            key=f"quiz_ans_{idx}",
            placeholder="Type your answer here..."
        )

        col1, col2 = st.columns([1, 3])
        submit_quiz = col1.button("Submit Answer", key=f"quiz_submit_{idx}")
        skip_quiz   = col2.button("Skip",          key=f"quiz_skip_{idx}")

        if submit_quiz and user_ans.strip():
            ans_lower = user_ans.strip().lower()

            # Validation: check if any keyword from the expected answer appears in the user answer
            is_correct = False
            if expected_answer:
                keywords = [w for w in expected_answer.split() if len(w) > 2]
                is_correct = any(kw in ans_lower for kw in keywords) if keywords else (ans_lower == expected_answer)
            else:
                # No expected answer stored — treat any non-empty response as attempted
                is_correct = None

            st.session_state.quiz_results.append({
                "question": question_text,
                "user_answer": user_ans.strip(),
                "correct": is_correct,
                "expected": qa.get("answer", "")
            })
            st.session_state.quiz_index += 1
            st.rerun()

        elif skip_quiz:
            st.session_state.quiz_results.append({
                "question": question_text,
                "user_answer": "(skipped)",
                "correct": False,
                "expected": qa.get("answer", "")
            })
            st.session_state.quiz_index += 1
            st.rerun()

    else:
        # ---- QUIZ COMPLETE: show score ----
        results = st.session_state.quiz_results
        correct_count = sum(1 for r in results if r["correct"] is True)
        total_answered = len(results)
        score_pct = round((correct_count / total_answered) * 100) if total_answered else 0

        st.success(f"✅ Quiz complete! Score: **{correct_count} / {total_answered}** ({score_pct}%)")

        for i, r in enumerate(results, 1):
            if r["correct"] is True:
                icon = "✅"
            elif r["correct"] is False:
                icon = "❌"
            else:
                icon = "🔘"

            with st.expander(f"{icon} Q{i}: {r['question']}"):
                st.write(f"**Your answer:** {r['user_answer']}")
                if r['expected']:
                    st.write(f"**Expected answer:** {r['expected']}")
                if r["correct"] is True:
                    st.success("Correct!")
                elif r["correct"] is False:
                    st.error("Not quite right.")
                else:
                    st.info("Noted.")

        if st.button("Try Another Quiz"):
            st.session_state.quiz_active = False
            st.session_state.quiz_questions = []
            st.session_state.quiz_index = 0
            st.session_state.quiz_results = []
            st.rerun()