from flask import Flask, request, jsonify, session, render_template, redirect, url_for, Response, send_file
from flask_cors import CORS
from dotenv import load_dotenv
import os, csv, io, re
from difflib import SequenceMatcher, get_close_matches

from database import (
    signup_user, login_user, get_user_by_id,
    save_memory, get_memory,
    save_chat, get_chat_history, delete_all_chat_history,
    clear_user_private_data,
    add_training_item, list_training, update_training_item, delete_training_item,
    append_to_training_csv, admin_login, list_users,
)
import ai_brain
import external_apis as ext
from fun_facts import choose_fun_fact, format_fun_fact
from ai_brain import (
    generate_response, extract_memory_from_message,
    normalize_input, is_cancel_word, is_yes_word,
    is_greeting, is_smalltalk, is_help_intent, is_valid_teach_question, try_math,
    build_prediction_context,
)

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "groot-secret-key-2024")
CORS(app)

# ─── PAGES ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("chat_page"))
    return render_template("index.html")

@app.route("/chat")
def chat_page():
    if "user_id" not in session:
        return redirect(url_for("index"))
    return render_template("chat.html", username=session.get("username"))

# ─── USER AUTH ────────────────────────────────────────────────────────────────
@app.route("/api/signup", methods=["POST"])
def signup():
    d = request.json or {}
    username = d.get("username", "").strip()
    email    = d.get("email", "").strip()
    password = d.get("password", "")
    age      = int(d.get("age", 8) or 8)
    if not username or not email or not password:
        return jsonify({"success": False, "error": "Please fill in all fields! 📝"})
    if len(password) < 6:
        return jsonify({"success": False, "error": "Password must be 6+ characters! 🔒"})
    user, err = signup_user(username, email, password, age)
    if err:
        return jsonify({"success": False, "error": err})
    save_memory(user["id"], "name", username)
    if age:
        save_memory(user["id"], "age", str(age))
    session["user_id"] = user["id"]
    session["username"] = username
    return jsonify({"success": True, "username": username})

@app.route("/api/login", methods=["POST"])
def login():
    d = request.json or {}
    user, err = login_user(d.get("email", "").strip(), d.get("password", ""))
    if err:
        return jsonify({"success": False, "error": err})
    session["user_id"]  = user["id"]
    session["username"] = user["username"]
    return jsonify({"success": True, "username": user["username"]})

@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})

# ─── CHAT ─────────────────────────────────────────────────────────────────────
TEACH_RE = re.compile(r"(?:the answer is|answer:|it is|teach you[: ])\s*(.+)", re.I)

TEACH_SUBJECTS = {
    "maths": {
        "title": "🔢 Maths Time!",
        "topics": ["addition", "subtraction", "multiplication", "division", "shapes", "counting"],
        "lessons": {
            "addition": "Addition means putting numbers together.\n\n2 + 3 = 5\n\nIf you have 2 apples 🍎 and get 3 more, you have 5 apples!",
            "subtraction": "Subtraction means taking away.\n\n5 - 2 = 3\n\nIf you have 5 stars ⭐ and give away 2, 3 stars are left.",
            "multiplication": "Multiplication is fast adding.\n\n3 x 2 means 3 groups of 2.\nThat makes 6! ✨",
            "division": "Division means sharing equally.\n\n6 snacks shared by 2 children gives each child 3 snacks. 😊",
            "shapes": "Shapes are forms we can see.\n\nA circle is round ⚪\nA square has 4 equal sides ◼️\nA triangle has 3 sides 🔺",
            "counting": "Counting means saying numbers in order.\n\n1, 2, 3, 4, 5...\nCounting helps us know how many things there are!",
        },
    },
    "science": {
        "title": "🌱 Science Time!",
        "topics": ["plants", "animals", "weather", "water", "body", "food chain"],
        "lessons": {
            "plants": "Plants are living things.\n\nThey need sunlight ☀️, water 💧, and air 🌿 to grow.\n\nA tiny seed can grow into a big tree!",
            "animals": "Animals are living things.\n\nThey need food, water, air, and a safe home.\nSome animals walk, some swim, and some fly! 🐾",
            "weather": "Weather tells us what the sky and air are like today.\n\nIt can be sunny ☀️, rainy 🌧️, windy 💨, or cloudy ☁️.",
            "water": "Water is very important.\n\nPeople, animals, and plants all need water to live. 💧",
            "body": "Your body helps you move, think, breathe, and play.\n\nYour eyes see 👀, your ears hear 👂, and your legs help you walk.",
            "food chain": "A food chain shows who eats what.\n\nGrass grows 🌱\nA rabbit eats grass 🐇\nA fox may eat the rabbit 🦊",
        },
    },
    "english": {
        "title": "📚 English Time!",
        "topics": ["nouns", "verbs", "adjectives", "sentences", "spelling"],
        "lessons": {
            "nouns": "A noun is a naming word.\n\nDog 🐶\nBook 📖\nSchool 🏫\n\nThese are nouns!",
            "verbs": "A verb is an action word.\n\nRun 🏃\nJump 🤸\nRead 📖\n\nVerbs tell us what someone does.",
            "adjectives": "An adjective describes something.\n\nBig elephant 🐘\nRed ball 🔴\nHappy child 😊",
            "sentences": "A sentence tells a complete idea.\n\nThe cat sleeps.\nI like apples.\n\nSentences start with a capital letter.",
            "spelling": "Spelling means putting letters in the right order.\n\nC-A-T spells cat 🐱\nB-O-O-K spells book 📖",
        },
    },
    "space": {
        "title": "🪐 Space Time!",
        "topics": ["planets", "moon", "stars", "sun", "astronauts"],
        "lessons": {
            "planets": "Planets are big round worlds in space.\n\nEarth is our planet 🌍.\nIt goes around the Sun.",
            "moon": "The Moon is Earth's neighbor in space.\n\nIt shines at night because sunlight bounces off it. 🌕",
            "stars": "Stars are giant balls of light in space.\n\nThey look tiny because they are very far away. ✨",
            "sun": "The Sun is a star.\n\nIt gives Earth light and warmth. ☀️",
            "astronauts": "Astronauts are people who travel into space.\n\nThey wear special suits to stay safe. 🚀",
        },
    },
    "animals": {
        "title": "🦁 Animals Time!",
        "topics": ["lions", "tigers", "fish", "birds", "mammals", "habitats"],
        "lessons": {
            "lions": "Lions are big cats.\n\nThey live in groups called prides and have loud roars. 🦁",
            "tigers": "Tigers are big striped cats.\n\nThey are strong, quiet hunters. 🐯",
            "fish": "Fish live in water.\n\nThey use fins to swim and gills to breathe in water. 🐟",
            "birds": "Birds have feathers and beaks.\n\nMany birds can fly, and some sing beautiful songs. 🐦",
            "mammals": "Mammals are animals that usually have fur or hair.\n\nCats, dogs, lions, and people are mammals.",
            "habitats": "A habitat is an animal's home.\n\nFish live in water 🐟\nBirds live in nests 🐦\nLions live on grasslands 🦁",
        },
    },
}

TEACH_TOPIC_TO_SUBJECT = {
    topic: subject
    for subject, data in TEACH_SUBJECTS.items()
    for topic in data["topics"]
}
TEACH_EXTRA_TOPIC_SUBJECTS = {
    "volcano": "science",
    "volcanoes": "science",
    "magnets": "science",
    "magnet": "science",
    "rain": "science",
    "clouds": "science",
    "cloud": "science",
    "earthquakes": "science",
    "earthquake": "science",
    "dinosaurs": "science",
    "dinosaur": "science",
    "planets": "space",
    "planet": "space",
    "moon": "space",
    "stars": "space",
    "star": "space",
    "sun": "space",
    "astronauts": "space",
    "astronaut": "space",
    "money": "maths",
    "time": "maths",
    "fractions": "maths",
    "fraction": "maths",
    "reading": "english",
    "story": "english",
    "stories": "english",
    "punctuation": "english",
    "zebra": "animals",
    "zebras": "animals",
    "elephant": "animals",
    "elephants": "animals",
    "whale": "animals",
    "whales": "animals",
}
TEACH_TOPIC_ALIASES = {
    "math": "maths",
    "maths": "maths",
    "science": "science",
    "english": "english",
    "space": "space",
    "animals": "animals",
    "animal": "animals",
    "solar system": "space",
    "the solar system": "space",
    "photosynthesis": "plants",
    "volcano": "volcanoes",
    "magnet": "magnets",
    "human body": "science",
    "the human body": "science",
    "plant": "plants",
    "verb": "verbs",
    "noun": "nouns",
    "adjective": "adjectives",
    "sentence": "sentences",
    "shape": "shapes",
    "planet": "planets",
    "star": "stars",
    "lion": "lions",
    "tiger": "tigers",
    "bird": "birds",
    "fish": "fish",
    "habitat": "habitats",
}
TEACH_INTENT_RE = re.compile(r"\b(teach me|explain|learn about|what is|what are|tell me about)\b", re.I)

# Quiz answer detection
QUIZ_ANSWER_RE = re.compile(r"^\s*([A-D])\s*[.):-]?\s*$|^(?:answer\s+is\s+|my answer\s+is\s+)?([A-D])\s*$", re.I)
QUIZ_LETTER_EXTRA = re.compile(r"^(?:i\s+(?:think|choose|pick|go with)\s+)?([A-D])\b", re.I)
QUIZ_CONTINUE_WORDS = {"yes", "yeah", "yep", "sure", "ok", "okay", "another", "try again", "again"}
QUIZ_STOP_WORDS = {"no", "nope", "not now", "stop", "cancel"}
QUIZ_SUBJECTS = {"science", "math", "maths", "english", "general"}

def clear_teaching_state():
    session.pop("pending_question", None)
    session.pop("pending_answer",   None)
    session.pop("last_unknown_q",   None)
    session.pop("conversation_mode", None)

def clear_quiz_state():
    session.pop("active_quiz", None)
    session.pop("waiting_for_quiz_continue", None)

def clear_all_quiz_state():
    clear_quiz_state()
    session.pop("quiz_subject", None)

def clear_temp_states_for_teach():
    clear_all_quiz_state()
    session.pop("pending_question", None)
    session.pop("pending_answer", None)
    session.pop("last_unknown_q", None)

def normalize_quiz_subject(subject):
    subject = (subject or "general").lower()
    return "math" if subject == "maths" else subject

def is_quiz_continue_word(msg):
    return normalize_input(msg).rstrip("?") in QUIZ_CONTINUE_WORDS

def is_quiz_stop_word(msg):
    return normalize_input(msg).rstrip("?") in QUIZ_STOP_WORDS

def extract_quiz_request_subject(msg):
    text = normalize_input(msg).rstrip("?")
    if not re.search(r"\b(quiz|test|trivia)\b", text):
        return None
    for subject in QUIZ_SUBJECTS:
        if re.search(rf"\b{subject}\b", text):
            return normalize_quiz_subject(subject)
    return None

def start_quiz(subject):
    subject = normalize_quiz_subject(subject)
    result = ext.get_quiz(subject)
    if not result:
        return None, {}
    extras = result.get("extras") or {}
    quiz = extras.get("quiz")
    if quiz:
        session["active_quiz"] = quiz
        session["quiz_subject"] = quiz.get("subject", subject)
        session.pop("waiting_for_quiz_continue", None)
    return result.get("reply", ""), extras

def quiz_subject_from_teach_subject(subject):
    if subject == "maths":
        return "math"
    return subject if subject in {"science", "english", "math"} else "general"

def normalize_teach_text(message):
    text = normalize_input(message).rstrip("?")
    text = re.sub(r"^(?:please\s+)?(?:teach me|explain|learn about|what is|what are|tell me about)\s*", "", text).strip()
    text = re.sub(r"^(?:about|the)\s+", "", text).strip()
    return TEACH_TOPIC_ALIASES.get(text, text)

def build_teach_prompt(subject):
    data = TEACH_SUBJECTS[subject]
    topics = "\n".join(f"* {topic}" for topic in data["topics"])
    return f"{data['title']}\n\nWhat would you like to learn about?\nYou can ask about things like:\n\n{topics}"

def build_teach_lesson(subject, topic):
    data = TEACH_SUBJECTS[subject]
    lesson = data["lessons"][topic]
    return f"{data['title']}\n\n{lesson}\n\nWant to learn another {subject} topic or try a mini quiz?"

def is_teach_menu_request(text):
    return text in {"another topic", "change topic", "new topic", "what can i learn", "what can i learn about", "topics", "show topics"}

def is_unclear_teach_topic(text):
    return not text or text in {"it", "that", "this", "thing", "things", "stuff", "something", "anything", "more"}

def teach_refusal():
    return "I can't teach that topic for kids. 🌿\n\nWe can learn something safe like plants, space, animals, numbers, or words!"

def teach_clarification():
    return "Do you mean animals, plants, space, numbers, or something else? 😊"

def teach_followup(subject, topic):
    return ""

def simplify_dataset_answer(answer):
    text = re.sub(r"\s+", " ", answer or "").strip()
    text = re.sub(r"^[^\w]*(?:[\w\s]+)?\*\*([^*]+)\*\*[^\w]*", r"\1. ", text).strip()
    text = re.sub(r"[*_`#>]", "", text)
    parts = re.split(r"(?<=[.!?])\s+", text)
    short = " ".join(parts[:2]).strip() if parts else text
    return short or text

def make_kid_friendly_teach_response(answer, subject, topic, source="unknown"):
    title = TEACH_SUBJECTS[subject]["title"]
    simple = simplify_dataset_answer(answer)
    if len(simple) > 320:
        simple = simple[:320].rsplit(" ", 1)[0].rstrip(".,;:") + "."
    if topic and topic.lower() not in simple.lower():
        simple = f"{topic.title()} is something interesting to learn about.\n\n{simple}"
    example = small_teach_example(subject, topic)
    return f"{title}\n\n{simple}\n\nExample:\n{example}" if example else f"{title}\n\n{simple}"

def small_teach_example(subject, topic):
    topic = (topic or "this").lower()
    if subject == "maths":
        return "You can use it when counting toys, snacks, or steps. 🔢"
    if subject == "english":
        return "You can try it in a short sentence today. 📚"
    if subject == "space":
        return "Look at the night sky and imagine where it belongs in space. 🪐"
    if subject == "animals":
        return "Think about where the animal lives and what it eats. 🐾"
    if "volcano" in topic:
        return "Lava can flow from a volcano when it erupts. 🌋"
    if "magnet" in topic:
        return "A fridge magnet can stick to a metal fridge. 🧲"
    return "You might spot clues about it in nature, at home, or at school. 🔎"

def tiny_teach_question(subject, topic):
    topic = (topic or "this topic").lower()
    if "volcano" in topic:
        return "What comes out of a volcano — lava or ice?"
    if "magnet" in topic:
        return "What might a magnet stick to — metal or paper?"
    if subject == "maths":
        return f"Where could you use {topic} today?"
    if subject == "english":
        return f"Can you make a sentence with {topic}?"
    if subject == "space":
        return "Would you like to learn another space idea next?"
    if subject == "animals":
        return f"Where do you think {topic} might live?"
    return f"What is one thing you noticed about {topic}?"

TEACH_FALLBACK_LESSONS = {
    "volcanoes": "A volcano is a mountain that can let out hot melted rock called lava.\n\nSome volcanoes sleep for a long time, and some can erupt. 🌋",
    "magnets": "A magnet can pull some metals toward it.\n\nMagnets have invisible pulling power. 🧲",
    "rain": "Rain is water that falls from clouds.\n\nIt helps plants grow and fills rivers and lakes. 🌧️",
    "clouds": "Clouds are made of tiny drops of water floating in the sky.\n\nSome clouds bring rain, and some just drift by. ☁️",
    "earthquakes": "An earthquake is when the ground shakes.\n\nIt happens because big pieces of Earth move deep below us.",
    "dinosaurs": "Dinosaurs were animals that lived a very long time ago.\n\nSome were huge, and some were small. 🦕",
    "money": "Money helps people buy and sell things.\n\nWe can count coins and notes to know how much we have.",
    "time": "Time helps us know when things happen.\n\nClocks show hours and minutes. 🕒",
    "fractions": "A fraction is a part of a whole.\n\nHalf a pizza is 1 out of 2 equal parts. 🍕",
    "reading": "Reading means looking at words and understanding them.\n\nBooks can tell stories and teach facts. 📖",
    "story": "A story tells what happens to people, animals, or make-believe characters.\n\nStories can be fun, silly, or exciting. 📚",
    "punctuation": "Punctuation marks help sentences make sense.\n\nA full stop ends a sentence. A question mark ends a question.",
}

def fallback_teach_lesson(subject, topic):
    lesson = TEACH_FALLBACK_LESSONS.get(topic)
    if not lesson:
        lesson = TEACH_SUBJECTS.get(subject, {}).get("lessons", {}).get(topic)
    if not lesson:
        if subject == "science":
            lesson = f"{topic.title()} is something we can explore in science.\n\nWe can ask what it is, how it works, and what we can see around us. 🔎"
        elif subject == "maths":
            lesson = f"{topic.title()} is something we can learn with numbers, shapes, or patterns.\n\nMaths helps us solve little puzzles step by step. 🔢"
        elif subject == "english":
            lesson = f"{topic.title()} is something we can learn with words.\n\nEnglish helps us read, write, speak, and share ideas. 📚"
        elif subject == "space":
            lesson = f"{topic.title()} is something we can wonder about in space.\n\nSpace is full of faraway things like planets, stars, and moons. 🪐"
        else:
            lesson = f"{topic.title()} is something we can learn about in the animal world.\n\nAnimals live, move, eat, and find homes in many different ways. 🐾"
    return lesson

def search_teach_csv(topic, subject=None):
    answer, _, conf = ai_brain.find_best_answer(topic)
    if answer and conf > 0.3:
        return answer
    answer, _, conf = ai_brain.find_best_answer(f"what is {topic}")
    if answer and conf > 0.3:
        return answer
    return None

def fetch_teach_from_api(topic, subject=None):
    api_calls = []
    if subject == "english":
        api_calls.append(lambda: ext.get_definition(topic))
    api_calls.extend([
        lambda: ext.get_wikipedia(topic),
        lambda: ext.get_duckduckgo(topic),
    ])
    for call in api_calls:
        try:
            result = call()
            if result and result.get("reply"):
                return result["reply"]
        except Exception:
            pass
    return None

def get_hardcoded_fallback(topic, subject=None):
    subject = subject if subject in TEACH_SUBJECTS else "science"
    topic = TEACH_TOPIC_ALIASES.get(topic, topic)
    return fallback_teach_lesson(subject, topic)

def ask_simple_clarification(topic, subject=None):
    return teach_clarification()

def get_teach_answer(topic, subject=None):
    subject = subject if subject in TEACH_SUBJECTS else "science"
    topic = normalize_teach_text(topic)
    if is_unclear_teach_topic(topic):
        return ask_simple_clarification(topic, subject)
    safe, redirect = ai_brain.check_moderation(topic)
    if not safe:
        return teach_refusal()
    csv_answer = search_teach_csv(topic, subject)
    if csv_answer:
        return make_kid_friendly_teach_response(csv_answer, subject, topic, source="csv")
    api_answer = fetch_teach_from_api(topic, subject)
    if api_answer:
        return make_kid_friendly_teach_response(api_answer, subject, topic, source="api")
    fallback_answer = get_hardcoded_fallback(topic, subject)
    if fallback_answer:
        return make_kid_friendly_teach_response(fallback_answer, subject, topic, source="fallback")
    return ask_simple_clarification(topic, subject)

def find_teach_subject_or_topic(message):
    text = normalize_teach_text(message)
    if text in TEACH_SUBJECTS:
        return text, None
    if text in TEACH_TOPIC_ALIASES:
        text = TEACH_TOPIC_ALIASES[text]
    if text in TEACH_EXTRA_TOPIC_SUBJECTS:
        return TEACH_EXTRA_TOPIC_SUBJECTS[text], text
    if text in TEACH_TOPIC_TO_SUBJECT:
        return TEACH_TOPIC_TO_SUBJECT[text], text
    for topic, subject in TEACH_EXTRA_TOPIC_SUBJECTS.items():
        if re.search(rf"\b{re.escape(topic)}\b", text):
            return subject, topic
    for topic, subject in TEACH_TOPIC_TO_SUBJECT.items():
        if re.search(rf"\b{re.escape(topic)}\b", text):
            return subject, topic
    for subject in TEACH_SUBJECTS:
        if re.search(rf"\b{subject}\b", text):
            return subject, None
    return None, None

def teach_subject_name(subject):
    return {"maths": "Maths", "science": "Science", "english": "English", "space": "Space", "animals": "Animals"}.get(subject, subject.title())

def build_any_teach_lesson(subject, topic):
    topic = TEACH_TOPIC_ALIASES.get(topic, topic)
    return get_teach_answer(topic, subject)

def start_teach_mode(subject):
    clear_temp_states_for_teach()
    session["conversation_mode"] = {"active": True, "mode": "teach", "subject": subject, "topic": None, "waiting_for": "topic"}
    return build_teach_prompt(subject)

def handle_teach_topic(message, mode):
    subject = mode.get("subject")
    if subject not in TEACH_SUBJECTS:
        session.pop("conversation_mode", None)
        return None
    requested_quiz_subject = extract_quiz_request_subject(message)
    if requested_quiz_subject or re.search(r"\b(quiz|test|trivia)\b", normalize_input(message)):
        session.pop("conversation_mode", None)
        reply, extras = start_quiz(requested_quiz_subject or quiz_subject_from_teach_subject(subject))
        return {"reply": reply, "extras": extras} if reply else None
    if TEACH_INTENT_RE.search(message):
        requested_subject, requested_topic = find_teach_subject_or_topic(message)
        if requested_subject and (requested_subject != subject or requested_topic is None):
            if requested_topic:
                clear_temp_states_for_teach()
                session["conversation_mode"] = {"active": True, "mode": "teach", "subject": requested_subject, "topic": requested_topic, "waiting_for": "follow_up"}
                return build_any_teach_lesson(requested_subject, requested_topic)
            return start_teach_mode(requested_subject)
    text = normalize_teach_text(message)
    if is_cancel_word(text) or text in {"stop", "exit", "quit"}:
        session.pop("conversation_mode", None)
        return "Okay, we can stop teaching for now 😊"
    if is_teach_menu_request(text):
        session["conversation_mode"] = {"active": True, "mode": "teach", "subject": subject, "topic": None, "waiting_for": "topic"}
        return build_teach_prompt(subject)
    if is_unclear_teach_topic(text):
        return teach_clarification()
    if mode.get("waiting_for") == "follow_up" and not TEACH_INTENT_RE.search(message):
        current_topic = mode.get("topic") or text
        follow_topic = f"{current_topic} {text}".strip()
        session["conversation_mode"] = {"active": True, "mode": "teach", "subject": subject, "topic": current_topic, "waiting_for": "follow_up"}
        return get_teach_answer(follow_topic, subject)
    topic = TEACH_TOPIC_ALIASES.get(text, text)
    detected_subject, detected_topic = find_teach_subject_or_topic(topic)
    if detected_subject and detected_topic and detected_subject != subject:
        session["conversation_mode"] = {"active": True, "mode": "teach", "subject": detected_subject, "topic": detected_topic, "waiting_for": "follow_up"}
        icon = TEACH_SUBJECTS[detected_subject]["title"].split()[0]
        intro = f"That sounds like {teach_subject_name(detected_subject)}! {icon} I can teach you about {detected_topic}.\n\n"
        return intro + build_any_teach_lesson(detected_subject, detected_topic)
    if topic not in TEACH_SUBJECTS[subject]["lessons"]:
        for candidate in TEACH_SUBJECTS[subject]["lessons"]:
            if re.search(rf"\b{re.escape(candidate)}\b", text):
                topic = candidate
                break
    session["conversation_mode"] = {"active": True, "mode": "teach", "subject": subject, "topic": topic, "waiting_for": "follow_up"}
    return build_any_teach_lesson(subject, topic)

def detect_new_teach_request(message):
    if not TEACH_INTENT_RE.search(message):
        return None, None
    return find_teach_subject_or_topic(message)

# Runtime Teach Me pipeline. This disables the older hardcoded lesson source above:
# subjects provide UI examples only; answers come from CSV, then API, then safe failure.
TEACH_SUBJECTS = {
    "maths": {
        "title": "🔢 Maths Time!",
        "examples": ["addition", "subtraction", "multiplication", "division", "shapes", "counting"],
    },
    "science": {
        "title": "🌱 Science Time!",
        "examples": ["plants", "animals", "weather", "water", "body", "food chain"],
    },
    "english": {
        "title": "📚 English Time!",
        "examples": ["nouns", "verbs", "adjectives", "sentences", "spelling"],
    },
    "space": {
        "title": "🪐 Space Time!",
        "examples": ["planets", "moon", "stars", "sun", "astronauts"],
    },
    "animals": {
        "title": "🦁 Animals Time!",
        "examples": ["lions", "tigers", "fish", "birds", "mammals", "habitats"],
    },
}

TEACH_SUBJECT_ALIASES = {"math": "maths", "maths": "maths", "science": "science", "english": "english", "space": "space", "animal": "animals", "animals": "animals"}
TEACH_TOPIC_TO_SUBJECT = {topic: subject for subject, data in TEACH_SUBJECTS.items() for topic in data["examples"]}
TEACH_TOPIC_ALIASES = {"math": "maths", "animal": "animals"}
TEACH_EXTRA_TOPIC_SUBJECTS = {}
TEACH_LOW_CONFIDENCE = 0.5

TEACH_STOPWORDS = {
    "a", "an", "the", "is", "are", "am", "do", "does", "did", "have", "has", "had",
    "what", "why", "how", "many", "much", "tell", "me", "about", "learn", "teach",
    "explain", "please", "can", "you", "i", "it", "that", "this", "of", "in", "on",
    "for", "to", "with", "and", "or", "doesnt", "dont"
}
TEACH_GENERIC_FOLLOWUP_TERMS = {"come", "comes", "out", "need", "shine", "side", "sides", "happen", "work", "make", "made"}
TEACH_RELEVANCE_TERMS = {
    "maths": {"addition", "add", "subtraction", "subtract", "multiplication", "multiply", "division", "divide", "shape", "shapes", "number", "numbers", "count", "counting", "square", "triangle", "circle", "rectangle", "side", "sides", "corner", "corners", "perimeter", "area", "fraction", "percent", "plus", "minus"},
    "science": {"plant", "plants", "weather", "water", "body", "food", "chain", "volcano", "volcanoes", "magnet", "magnets", "gravity", "force", "light", "sound", "animal", "animals", "rain", "cloud", "clouds", "energy", "air", "oxygen"},
    "english": {"noun", "nouns", "verb", "verbs", "adjective", "adjectives", "sentence", "sentences", "spelling", "spell", "word", "words", "letter", "letters", "grammar", "meaning", "synonym", "antonym", "paragraph"},
    "space": {"space", "planet", "planets", "moon", "star", "stars", "sun", "astronaut", "astronauts", "solar", "system", "galaxy", "earth", "mars", "jupiter", "saturn", "rocket"},
    "animals": {"animal", "animals", "lion", "lions", "tiger", "tigers", "fish", "bird", "birds", "mammal", "mammals", "habitat", "habitats", "elephant", "elephants", "whale", "whales", "zebra", "zebras", "pet", "wildlife"},
}
GLOBAL_TEACH_BYPASS_RE = re.compile(
    r"\b("
    r"fun fact|joke|tell me a joke|show me|generate image|picture|image|photo|pic|"
    r"astronomy picture|picture of the day|apod|nasa picture|space picture|"
    r"video|youtube|play me|quiz|quiz me|test me|trivia|help|what can you do|"
    r"who are you|what are you|your name|groot ai"
    r")\b",
    re.I,
)

COMMON_TEACH_TYPOS = {
    "squire": "square",
    "triangel": "triangle",
    "plannet": "planet",
    "plannets": "planets",
    "animels": "animals",
    "animel": "animal",
    "volcanos": "volcanoes",
    "sentance": "sentence",
    "sentances": "sentences",
    "substraction": "subtraction",
    "multipication": "multiplication",
}

def _teach_clean(text):
    return re.sub(r"\s+", " ", normalize_input(text or "")).strip()

def _teach_stem(word):
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("oes") and len(word) > 4:
        return word[:-2]
    if word.endswith("ces") and len(word) > 4:
        return word[:-1]
    if word.endswith("es") and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and len(word) > 3:
        return word[:-1]
    return word

def _teach_tokens(text):
    return [_teach_stem(w) for w in re.findall(r"[a-z0-9]+", _teach_clean(text)) if w not in TEACH_STOPWORDS]

def is_global_teach_bypass_intent(message):
    text = _teach_clean(message)
    return bool(
        GLOBAL_TEACH_BYPASS_RE.search(text)
        or is_greeting(text)
        or is_smalltalk(text)
        or is_help_intent(text)
        or detect_spelling_intent(text) is not None
    )

def is_fun_fact_intent(message):
    return bool(re.search(r"\b(?:tell me a )?fun fact\b", _teach_clean(message)))

def _teach_vocab():
    vocab = set(TEACH_SUBJECT_ALIASES) | set(TEACH_TOPIC_TO_SUBJECT)
    for row in getattr(ai_brain, "DATASET", []):
        for field in ("question", "keywords", "topic"):
            vocab.update(_teach_tokens(row.get(field, "")))
    return {w for w in vocab if len(w) > 2}

def extract_teach_query(user_message, teach_state):
    text = _teach_clean(user_message)
    text = re.sub(r"^(?:please\s+)?(?:teach me|explain|learn about|tell me about|what is|what are)\s*", "", text).strip()
    text = re.sub(r"^(?:about|the)\s+", "", text).strip()
    current_topic = (teach_state or {}).get("topic")
    if current_topic and re.fullmatch(r"(?:what|why|how|where|when|who)?\s*(?:about|more|it|that|this)?", text or ""):
        return current_topic
    meaningful_terms = [t for t in _teach_tokens(text) if t not in TEACH_GENERIC_FOLLOWUP_TERMS]
    if current_topic and not meaningful_terms:
        if re.search(r"\b(why|how|what|where|when|does|do|can)\b", text):
            return f"{current_topic} {text}".strip()
    return text

def normalize_child_question(topic_or_question, subject=None, teach_state=None):
    text = _teach_clean(topic_or_question)
    if not text:
        return "", 0.0

    words = text.split()
    vocab = _teach_vocab()
    corrected = []
    confidence = 0.75 if any(len(w) > 3 for w in words) else 0.45

    for word in words:
        replacement = COMMON_TEACH_TYPOS.get(word)
        if replacement:
            corrected.append(replacement)
            confidence = max(confidence, 0.82)
            continue
        if len(word) > 4 and word.isalpha() and word not in vocab and word not in TEACH_STOPWORDS:
            match = get_close_matches(word, vocab, n=1, cutoff=0.78)
            if match:
                ratio = SequenceMatcher(None, word, match[0]).ratio()
                corrected.append(match[0])
                confidence = min(confidence, max(0.55, ratio))
                continue
        corrected.append(word)

    text = " ".join(corrected)
    text = re.sub(r"\bhow many sides ([a-z]+) have\b", r"how many sides does a \1 have", text)
    text = re.sub(r"\bwhy ([a-z]+) shine\b", r"why does the \1 shine", text)
    text = re.sub(r"\bplants drink water\b", "do plants need water", text)
    text = re.sub(r"\bplant drink water\b", "do plants need water", text)

    useful = _teach_tokens(text)
    if not useful:
        confidence = 0.0
    elif any(t in vocab for t in useful):
        confidence = max(confidence, 0.72)
    return text, min(confidence, 1.0)

def _dataset_score(query_tokens, row):
    row_text = " ".join([row.get("question", ""), row.get("keywords", ""), row.get("topic", "")])
    row_tokens = set(_teach_tokens(row_text))
    if not query_tokens or not row_tokens:
        return 0.0
    overlap = len(set(query_tokens) & row_tokens)
    score = overlap / max(len(set(query_tokens)), 1)
    clean_query = " ".join(query_tokens)
    clean_row = " ".join(row_tokens)
    if clean_query and clean_query in clean_row:
        score += 0.25
    return score

def search_dataset(normalized_query, subject=None):
    query_tokens = _teach_tokens(normalized_query)
    if not query_tokens:
        return None
    best = None
    best_score = 0.0
    for row in getattr(ai_brain, "DATASET", []):
        score = _dataset_score(query_tokens, row)
        if score > best_score:
            best, best_score = row, score
    if re.search(r"\bhow many sides?\b", normalized_query):
        best_blob = " ".join([
            (best or {}).get("question", ""),
            (best or {}).get("keywords", ""),
            (best or {}).get("answer", ""),
        ]).lower()
        if "how many sides" not in best_blob and "how many side" not in best_blob and "side" not in best_blob:
            return None
    if best and best_score >= 0.62:
        return best.get("answer")
    return None

def expand_teach_query(normalized_query, subject=None):
    focus = _focus_topic(normalized_query)
    if subject == "english":
        return f"english grammar {focus} explanation for kids"
    if subject == "space":
        return f"{focus} space explanation for kids"
    if subject == "maths":
        return f"{normalized_query} maths explanation for kids"
    if subject == "animals":
        return f"{focus} animal explanation for kids"
    if subject == "science":
        return f"{focus} science explanation for children"
    return f"{normalized_query} explanation for kids"

BAD_RETRIEVAL_PATTERNS = re.compile(
    r"\b(written by|published|middle ages|volume|theology|disambiguation|compendium|"
    r"book title|novel|treatise|bibliography|dictionary entry)\b",
    re.I,
)

def is_incomplete_or_bad_result(answer):
    text = _teach_clean(answer)
    if not text or len(text) < 35:
        return True
    if BAD_RETRIEVAL_PATTERNS.search(text):
        return True
    if re.search(r"(\.\.\.|…)\s*$", text):
        return True
    if re.search(r"\b(to serve as a|refers to the array of resources)\.?$", text, re.I):
        return True
    return False

def _focus_topic(normalized_query):
    tokens = _teach_tokens(normalized_query)
    if not tokens:
        return normalized_query
    for token in reversed(tokens):
        if token not in {"side", "need", "shine", "many"}:
            return token
    return tokens[-1]

def detect_spelling_intent(message):
    text = _teach_clean(message)
    patterns = [
        r"\bspelling of\s+(.+)$",
        r"\bhow to spell\s+(.+)$",
        r"\bcan you spell\s+(.+)$",
        r"\bspell\s+(.+)$",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            target = re.sub(r"[^a-zA-Z\s-]", " ", m.group(1)).strip()
            target = re.sub(r"\s+", " ", target)
            return target or None
    if text == "spelling":
        return ""
    return None

def format_spelling_response(target):
    title = TEACH_SUBJECTS["english"]["title"]
    if target == "":
        return f"{title}\n\nWhat word would you like me to spell?"
    words = [w for w in re.findall(r"[a-zA-Z]+", target) if w]
    if not words:
        return f"{title}\n\nWhat word would you like me to spell?"
    spelled = "  ".join("-".join(word.upper()) for word in words)
    display = " ".join(word.capitalize() for word in words)
    letters = sum(len(word) for word in words)
    return f"{title}\n\nThe spelling is:\n\n{spelled}\n\n“{display}” has {letters} letters."

def call_learning_api(normalized_query, subject=None):
    focus = _focus_topic(normalized_query)
    expanded_query = expand_teach_query(normalized_query, subject)
    api_calls = []
    if subject == "english" and re.search(r"\b(meaning|define|definition)\b", normalized_query):
        api_calls.append(lambda: ext.get_definition(focus))
    api_calls.extend([
        lambda: ext.get_duckduckgo(expanded_query),
        lambda: ext.get_wikipedia(expanded_query),
        lambda: ext.get_duckduckgo(normalized_query),
        lambda: ext.get_wikipedia(f"{focus} for kids"),
        lambda: ext.get_wikipedia(focus),
        lambda: ext.get_duckduckgo(focus),
    ])
    for call in api_calls:
        try:
            result = call()
            if result and result.get("reply") and not is_incomplete_or_bad_result(result["reply"]):
                return result["reply"]
        except Exception:
            pass
    return None

def _plain_answer(raw_answer):
    text = re.sub(r"^[^\w]*(?:[\w\s]+)?\*\*([^*]+)\*\*[^\w]*", r"\1. ", raw_answer or "")
    text = re.sub(r"[*_`#>]", "", text)
    text = re.sub(r"ðŸ..|🔎|👉|💡|📖", "", text)
    text = re.sub(r"\b(?:anamniotic|cranium|digits|vertebrate|vertebrates|aquatic)\b,?\s*", "", text, flags=re.I)
    text = re.sub(r"\bgill-bearing\b", "has gills", text, flags=re.I)
    text = re.sub(r"\bIn ecology,\s*", "", text, flags=re.I)
    text = re.sub(r"\brefers to\b", "means", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\bregular quadrilateral\b", "shape", text, flags=re.I)
    text = re.sub(r"\bquadrilateral\b", "4-sided shape", text, flags=re.I)
    text = re.sub(r"\bvertices\b", "corners", text, flags=re.I)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    simple = " ".join(sentences[:3]).strip()
    simple = re.sub(r"\s*(?:\.{3}|…)+\s*$", ".", simple).strip()
    if simple.endswith(",") or simple.endswith(";") or simple.endswith(":"):
        simple = simple[:-1] + "."
    if simple and simple[-1] not in ".!?":
        simple += "."
    return simple

def _supported_example(simple, query):
    q = query.lower()
    s = simple.lower()
    if "square" in q and ("4" in s or "four" in s or "equal sides" in s):
        return "Look at a window, tile, or box face. It may be square. ◼️"
    if "triangle" in q and ("3" in s or "three" in s):
        return "A slice of pizza can look like a triangle. 🔺"
    if "plant" in q and ("water" in s or "sun" in s):
        return "A small plant grows better with water and sunlight. 🌱"
    if "moon" in q and ("sun" in s or "light" in s or "reflect" in s):
        return "The Moon looks bright at night because sunlight bounces from it. 🌕"
    if "fish" in q:
        return "A goldfish is small, but a shark is very big."
    if "sentence" in q:
        return "“I like apples.”"
    if "astronaut" in q:
        return "Astronauts train before they go into space."
    return None

def _rewrite_known_kid_answer(simple, subject, query):
    q = query.lower()
    if subject == "english" and re.search(r"\bsentences?\b", q):
        return "A sentence is a group of words that gives a complete idea.\n\nSentences usually start with a capital letter and end with a punctuation mark."
    if subject == "english" and re.search(r"\bnouns?\b", q):
        return "A noun is a naming word.\n\nIt can name a person, place, animal, thing, or idea."
    if subject == "english" and re.search(r"\bverbs?\b", q):
        return "A verb is an action word.\n\nIt tells what someone or something does."
    if subject == "english" and re.search(r"\badjectives?\b", q):
        return "An adjective is a describing word.\n\nIt tells more about a noun, like big, red, or happy."
    if subject == "space" and re.search(r"\bastronauts?\b", q):
        return "Astronauts are people who travel into space 🚀\n\nThey wear special suits and ride rockets or spacecraft to explore beyond Earth."
    if subject == "animals" and "fish" in q:
        return "Fish are animals that live in water. 🐟\n\nThey breathe using gills and swim using fins.\n\nThey can be small like a goldfish or big like a shark."
    if "habitat" in q:
        return "A habitat is the place where a living thing lives.\n\nIt gives animals or plants food, water, shelter, and space."
    if "plant" in q and ("need" in q or "water" in q):
        return "Plants need sunlight, water, air, and space to grow.\n\nA tiny seed can become a healthy plant when it gets what it needs. 🌱"
    return simple

def format_kid_friendly(raw_answer, subject, normalized_query, source="unknown"):
    simple = _plain_answer(raw_answer)
    if not simple:
        return safe_teach_failure()
    simple = _rewrite_known_kid_answer(simple, subject, normalized_query)
    title = TEACH_SUBJECTS.get(subject, TEACH_SUBJECTS["science"])["title"]
    example = _supported_example(simple, normalized_query)
    parts = [title, "", simple]
    if example:
        parts.extend(["", "Example:", example])
    return "\n".join(parts)

make_kid_friendly_teach_response = format_kid_friendly

def ask_clarification(normalized_query, subject=None):
    if normalized_query:
        return f"Do you mean **{normalized_query}**? 😊\n\nCan you ask it one more simple way?"
    return "Do you mean animals, plants, space, numbers, or something else? 😊"

def safe_teach_failure():
    return "I'm not sure about that yet 😊 Can you ask it in a simpler way or choose another topic?"

def ask_clarification_or_safe_failure(normalized_query, subject=None):
    return safe_teach_failure()

def get_teach_response(user_message, teach_state):
    subject = (teach_state or {}).get("subject") or "science"
    spelling_target = detect_spelling_intent(user_message)
    if spelling_target is not None:
        return format_spelling_response(spelling_target), spelling_target or "spelling", "spelling"
    topic_or_question = extract_teach_query(user_message, teach_state or {})
    normalized_query, confidence = normalize_child_question(topic_or_question, subject, teach_state)
    if confidence < TEACH_LOW_CONFIDENCE:
        return ask_clarification(normalized_query, subject), normalized_query, "clarify"
    safe, _ = ai_brain.check_moderation(normalized_query)
    if not safe:
        return teach_refusal(), normalized_query, "refused"
    csv_answer = search_dataset(normalized_query, subject)
    if csv_answer:
        return format_kid_friendly(csv_answer, subject, normalized_query, source="csv"), normalized_query, "csv"
    api_answer = call_learning_api(normalized_query, subject)
    if api_answer:
        return format_kid_friendly(api_answer, subject, normalized_query, source="api"), normalized_query, "api"
    return ask_clarification_or_safe_failure(normalized_query, subject), normalized_query, "failed"

def search_teach_csv(topic, subject=None):
    normalized_query, confidence = normalize_child_question(topic, subject, {})
    if confidence < TEACH_LOW_CONFIDENCE:
        return None
    return search_dataset(normalized_query, subject)

def fetch_teach_from_api(topic, subject=None):
    normalized_query, confidence = normalize_child_question(topic, subject, {})
    if confidence < TEACH_LOW_CONFIDENCE:
        return None
    return call_learning_api(normalized_query, subject)

def get_teach_answer(topic, subject=None):
    reply, _, _ = get_teach_response(topic, {"active": True, "mode": "teach", "subject": subject or "science", "topic": None, "waiting_for": "topic"})
    return reply

def normal_chat_response(user_id, username, message, memory, active_quiz=None):
    extras = {}
    spelling_target = detect_spelling_intent(message)
    if spelling_target is not None:
        reply = format_spelling_response(spelling_target)
        result = {"reply": reply, "known": True}
    elif is_fun_fact_intent(message):
        item = choose_fun_fact(message, session.get("last_fun_fact"))
        reply = format_fun_fact(item)
        if item:
            session["last_fun_fact"] = item["fact"]
        result = {"reply": reply, "known": True}
    else:
        history = get_chat_history(user_id, 20)
        prediction_ctx = build_prediction_context(history, memory)
        result = generate_response(message, memory, history=history, prediction_ctx=prediction_ctx)
        reply = result["reply"]
        extras = result.get("extras") or {}

    if extras and extras.get("quiz"):
        session["active_quiz"] = extras["quiz"]
        session["quiz_subject"] = extras["quiz"].get("subject", "general")
        session.pop("waiting_for_quiz_continue", None)
    elif active_quiz:
        clear_quiz_state()

    if not result.get("known") and result.get("teachable"):
        add_training_item(user_id, username, message, answer=None, source="unknown")
        session["pending_question"] = message
        session.pop("pending_answer", None)
        session["last_unknown_q"] = message

    save_chat(user_id, message, reply, extras)
    resp = {"reply": reply, "known": result.get("known", True), "extras": extras}
    if result.get("correction_note"):
        resp["correction_note"] = result["correction_note"]
    return jsonify(resp)

NAME_INTENT_RE = re.compile(
    r"^\s*(?:my\s+name\s+is|call\s+me|i\s+am\s+called)\s+([A-Za-z][A-Za-z\s'-]{0,30})[.!?]?\s*$",
    re.I,
)
NAME_BLOCKLIST = {
    "a", "b", "c", "d", "hi", "hello", "hey", "yes", "no", "ok", "okay",
    "quiz", "teach", "math", "maths", "science", "english", "space", "animals",
    "fun", "fact", "help", "joke", "what", "why", "how", "show", "tell",
    "give", "spell", "image", "picture", "good", "morning", "afternoon",
    "evening", "night", "thanks", "thank", "bye", "goodbye",
}
NAME_PHRASE_BLOCKLIST = {
    "good morning", "good afternoon", "good evening", "good night",
    "good bye", "goodbye", "thank you", "thanks", "how are you",
}
TIME_GREETING_RE = re.compile(r"^\s*(?:good\s+)?(?:morning|afternoon|evening|night)\s*[.!?]*\s*$", re.I)

def _set_waiting_for_name(waiting):
    state = session.get("conversation_state") or {}
    if not isinstance(state, dict):
        state = {}
    state["waiting_for_name"] = bool(waiting)
    session["conversation_state"] = state

def _clean_child_name(raw_name):
    name = re.sub(r"[^A-Za-z\s'-]", "", raw_name or "").strip()
    name = re.sub(r"\s+", " ", name)
    if not name:
        return None
    if name.lower() in NAME_PHRASE_BLOCKLIST:
        return None
    words = name.split()
    if len(words) > 2:
        return None
    if any(w.lower() in NAME_BLOCKLIST for w in words):
        return None
    return " ".join(w.capitalize() for w in words)

def detect_name_response(message, waiting_for_name=False):
    direct = NAME_INTENT_RE.match(message or "")
    if direct:
        return _clean_child_name(direct.group(1))
    if not waiting_for_name:
        return None
    text = (message or "").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z\s'-]{0,30}", text):
        return None
    return _clean_child_name(text)

def _save_json_reply(user_id, message, reply, known=True, extras=None):
    extras = extras or {}
    save_chat(user_id, message, reply, extras)
    payload = {"reply": reply, "known": known}
    if extras:
        payload["extras"] = extras
    return jsonify(payload)

def handle_global_intent(user_id, username, message, memory, active_quiz=None):
    state = session.get("conversation_state") or {}
    waiting_for_name = bool(isinstance(state, dict) and state.get("waiting_for_name"))

    if is_greeting(message):
        clear_teaching_state()
        clear_all_quiz_state()
        known_name = _clean_child_name((memory or {}).get("name", ""))
        if known_name:
            _set_waiting_for_name(False)
            return _save_json_reply(user_id, message, f"Hi {known_name}! 🌿 What would you like to learn today?")
        _set_waiting_for_name(True)
        return _save_json_reply(user_id, message, "Hi there! 🌿 I am Groot! What's your name?")

    if TIME_GREETING_RE.match(message or ""):
        clear_teaching_state()
        clear_all_quiz_state()
        _set_waiting_for_name(False)
        return normal_chat_response(user_id, username, message, memory, None)

    name = detect_name_response(message, waiting_for_name)
    if name:
        clear_teaching_state()
        clear_all_quiz_state()
        save_memory(user_id, "name", name)
        memory["name"] = name
        _set_waiting_for_name(False)
        return _save_json_reply(user_id, message, f"Nice to meet you, {name}! 😊")

    math_reply = try_math(message)
    if math_reply:
        clear_teaching_state()
        clear_all_quiz_state()
        _set_waiting_for_name(False)
        return _save_json_reply(user_id, message, math_reply)

    requested_quiz_subject = extract_quiz_request_subject(message)
    if requested_quiz_subject or re.search(r"\b(quiz|quiz me|test me|trivia)\b", normalize_input(message)):
        session.pop("conversation_mode", None)
        _set_waiting_for_name(False)
        reply, extras = start_quiz(requested_quiz_subject or "general")
        if reply:
            return _save_json_reply(user_id, message, reply, True, extras)

    if is_global_teach_bypass_intent(message):
        clear_teaching_state()
        clear_all_quiz_state()
        _set_waiting_for_name(False)
        return normal_chat_response(user_id, username, message, memory, None)

    return None

def build_teach_prompt(subject):
    data = TEACH_SUBJECTS[subject]
    examples = ", ".join(data["examples"])
    return f"{data['title']}\n\nWhat would you like to learn about?\nYou can ask about things like {examples}, or any {teach_subject_name(subject).lower()} question."

def find_teach_subject_or_topic(message):
    text = _teach_clean(message)
    stripped = re.sub(r"^(?:please\s+)?(?:teach me|explain|learn about|tell me about|what is|what are)\s*", "", text).strip()
    stripped = re.sub(r"^(?:about|the)\s+", "", stripped).strip()
    subject = TEACH_SUBJECT_ALIASES.get(stripped)
    if subject:
        return subject, None
    for key, value in TEACH_SUBJECT_ALIASES.items():
        if re.search(rf"\b{re.escape(key)}\b", stripped):
            return value, None
    for topic, topic_subject in TEACH_TOPIC_TO_SUBJECT.items():
        if re.search(rf"\b{re.escape(topic)}\b", stripped):
            return topic_subject, stripped
    return None, stripped if stripped and TEACH_INTENT_RE.search(message) else None

def detect_new_teach_request(message):
    if not TEACH_INTENT_RE.search(message):
        return None, None
    subject, topic = find_teach_subject_or_topic(message)
    if not subject and topic:
        return "science", topic
    return subject, topic

def build_any_teach_lesson(subject, topic):
    state = {"active": True, "mode": "teach", "subject": subject, "topic": None, "waiting_for": "topic"}
    reply, normalized_query, _ = get_teach_response(topic, state)
    return reply

def start_teach_mode(subject):
    clear_temp_states_for_teach()
    session["conversation_mode"] = {"active": True, "mode": "teach", "subject": subject, "topic": None, "waiting_for": "topic"}
    return build_teach_prompt(subject)

def _subject_from_query(normalized_query, current_subject):
    tokens = set(_teach_tokens(normalized_query))
    scores = {}
    for subject, data in TEACH_SUBJECTS.items():
        subject_words = {_teach_stem(w) for w in data["examples"]} | {_teach_stem(subject)}
        scores[subject] = len(tokens & subject_words)
    best_subject = max(scores, key=scores.get)
    if scores[best_subject] > 0 and best_subject != current_subject:
        return best_subject
    return current_subject

def detect_teach_relevance(message, current_subject, current_topic=None):
    text = _teach_clean(message)
    if not text:
        return 0.0
    if is_global_teach_bypass_intent(text):
        return 0.0
    if is_cancel_word(text) or text in {"stop", "exit", "quit", "no", "not now"}:
        return 1.0
    if is_teach_menu_request(text) or TEACH_INTENT_RE.search(text):
        return 1.0

    tokens = set(_teach_tokens(text))
    if not tokens:
        return 0.0

    subject_terms = set(TEACH_RELEVANCE_TERMS.get(current_subject, set()))
    subject_terms.update(_teach_stem(t) for t in TEACH_SUBJECTS.get(current_subject, {}).get("examples", []))
    subject_terms.add(_teach_stem(current_subject))

    score = 0.0
    if tokens & subject_terms:
        score = max(score, 0.7)

    if current_topic:
        topic_tokens = set(_teach_tokens(current_topic))
        if tokens & topic_tokens:
            score = max(score, 0.8)
        if tokens <= TEACH_GENERIC_FOLLOWUP_TERMS and re.search(r"\b(what|why|how|where|when|does|do|can)\b", text):
            score = max(score, 0.65)

    if re.search(r"\b(what|why|how|does|do|can|explain)\b", text) and (tokens & subject_terms):
        score = max(score, 0.75)
    return score

def handle_teach_topic(message, mode):
    subject = mode.get("subject")
    if subject not in TEACH_SUBJECTS:
        session.pop("conversation_mode", None)
        return None
    requested_quiz_subject = extract_quiz_request_subject(message)
    if requested_quiz_subject or re.search(r"\b(quiz|test|trivia)\b", normalize_input(message)):
        session.pop("conversation_mode", None)
        reply, extras = start_quiz(requested_quiz_subject or quiz_subject_from_teach_subject(subject))
        return {"reply": reply, "extras": extras} if reply else None
    text = _teach_clean(message)
    if is_cancel_word(text) or text in {"stop", "exit", "quit", "no", "not now"}:
        session.pop("conversation_mode", None)
        return "Okay, we can stop teaching for now 😊"
    if is_teach_menu_request(text):
        session["conversation_mode"] = {"active": True, "mode": "teach", "subject": subject, "topic": None, "waiting_for": "topic"}
        return build_teach_prompt(subject)
    explicit_subject, explicit_topic = detect_new_teach_request(message)
    if explicit_subject:
        subject = explicit_subject
        if explicit_topic is None:
            return start_teach_mode(subject)
    reply, normalized_query, source = get_teach_response(message, {"subject": subject, "topic": mode.get("topic"), "waiting_for": mode.get("waiting_for")})
    answer_subject = _subject_from_query(normalized_query, subject)
    if answer_subject != subject and source not in {"clarify", "failed", "refused"}:
        subject = answer_subject
        reply = f"That sounds like {teach_subject_name(subject)}! {TEACH_SUBJECTS[subject]['title'].split()[0]} I can teach you about it.\n\n" + reply
    if source not in {"clarify", "failed", "refused"}:
        session["conversation_mode"] = {"active": True, "mode": "teach", "subject": subject, "topic": normalized_query, "waiting_for": "follow_up"}
    return reply

def is_learning_interrupt(message):
    return (try_math(message) or is_greeting(message) or
            is_smalltalk(message) or is_help_intent(message) or
            is_valid_teach_question(message))

def check_quiz_answer(user_msg, quiz_data):
    """Check if user message is answering an active quiz. Returns reply or None."""
    options = quiz_data.get("options", [])
    correct = quiz_data.get("correct", "")
    explanation = quiz_data.get("explanation", "")
    subject = normalize_quiz_subject(quiz_data.get("subject") or session.get("quiz_subject"))

    msg = user_msg.strip()

    m = QUIZ_ANSWER_RE.match(msg) or QUIZ_LETTER_EXTRA.match(msg)
    chosen_text = None

    if m:
        chosen_letter = (m.group(1) or m.group(2) or "").upper()
        idx = ord(chosen_letter) - ord("A")
        if 0 <= idx < len(options):
            chosen_text = options[idx]
    else:
        msg_lower = msg.lower().strip()
        for opt in options:
            if msg_lower == opt.lower().strip() or msg_lower in opt.lower():
                chosen_text = opt
                break

    if not chosen_text:
        return None

    session.pop("active_quiz", None)
    session["waiting_for_quiz_continue"] = True
    session["quiz_subject"] = subject

    answer_line = f"The answer is **{correct}**."
    explanation_line = f"\n\n{explanation}" if explanation else ""
    again_line = f"\n\nWant to try another {subject} quiz?"

    if chosen_text.strip().lower() == correct.strip().lower():
        return f"🎉 **Correct! Well done!** ✅\n\n{answer_line}{explanation_line}{again_line}"
    return f"😅 **Not quite!**\n\n{answer_line}{explanation_line}{again_line}"

@app.route("/api/chat", methods=["POST"])
def chat():
    if "user_id" not in session:
        return jsonify({"error": "Please login first! 🔑"}), 401

    user_id  = session["user_id"]
    username = session.get("username", "user")
    message  = (request.json or {}).get("message", "").strip()
    if not message:
        return jsonify({"reply": "Please type something! 😊"})

    memory           = get_memory(user_id)
    normalized       = normalize_input(message)
    pending_question = session.get("pending_question") or session.get("last_unknown_q")
    pending_answer   = session.get("pending_answer")
    active_quiz      = session.get("active_quiz")
    waiting_quiz     = session.get("waiting_for_quiz_continue")

    global_response = handle_global_intent(user_id, username, message, memory, active_quiz)
    if global_response:
        return global_response

    # ── 0. Quiz answer check ──────────────────────────────────────────────────
    if active_quiz:
        quiz_reply = check_quiz_answer(message, active_quiz)
        if quiz_reply:
            save_chat(user_id, message, quiz_reply)
            return jsonify({"reply": quiz_reply, "known": True})

    conversation_mode = session.get("conversation_mode") or {}
    if conversation_mode.get("mode") == "teach" and conversation_mode.get("active"):
        relevance = detect_teach_relevance(message, conversation_mode.get("subject"), conversation_mode.get("topic"))
        if relevance < 0.5:
            session.pop("conversation_mode", None)
            return normal_chat_response(user_id, username, message, memory, active_quiz)
        teach_result = handle_teach_topic(message, conversation_mode)
        if isinstance(teach_result, dict):
            reply = teach_result.get("reply")
            extras = teach_result.get("extras") or {}
            save_chat(user_id, message, reply, extras)
            return jsonify({"reply": reply, "known": True, "extras": extras})
        if teach_result:
            save_chat(user_id, message, teach_result)
            return jsonify({"reply": teach_result, "known": True})

    teach_subject, teach_topic = detect_new_teach_request(message)
    if teach_subject:
        if teach_topic:
            clear_temp_states_for_teach()
            session["conversation_mode"] = {"active": True, "mode": "teach", "subject": teach_subject, "topic": teach_topic, "waiting_for": "follow_up"}
            reply = build_any_teach_lesson(teach_subject, teach_topic)
        else:
            reply = start_teach_mode(teach_subject)
        save_chat(user_id, message, reply)
        return jsonify({"reply": reply, "known": True})

    requested_quiz_subject = extract_quiz_request_subject(message)
    if requested_quiz_subject:
        reply, extras = start_quiz(requested_quiz_subject)
        if reply:
            save_chat(user_id, message, reply, extras)
            return jsonify({"reply": reply, "known": True, "extras": extras})

    # ── 0b. Quiz continuation check ──────────────────────────────────────────
    if waiting_quiz:
        if is_quiz_continue_word(message):
            subject = session.get("quiz_subject", "general")
            reply, extras = start_quiz(subject)
            if reply:
                save_chat(user_id, message, reply, extras)
                return jsonify({"reply": reply, "known": True, "extras": extras})
        if is_quiz_stop_word(message):
            subject = session.get("quiz_subject", "general")
            clear_all_quiz_state()
            reply = f"Okay! We can stop the {subject} quiz for now 😊"
            save_chat(user_id, message, reply)
            return jsonify({"reply": reply, "known": True})
        reply = "Please say yes to try another quiz, or no to stop 😊"
        save_chat(user_id, message, reply)
        return jsonify({"reply": reply, "known": True})

    # ── 1. Confirmation flow ──────────────────────────────────────────────────
    if pending_question and pending_answer:
        if is_cancel_word(normalized):
            clear_teaching_state()
            reply = "That's okay 😊"
            save_chat(user_id, message, reply)
            return jsonify({"reply": reply, "known": True})
        if is_yes_word(normalized):
            add_training_item(user_id, username, pending_question,
                              answer=pending_answer, source="user_taught")
            clear_teaching_state()
            reply = "Thank you! I've sent that to my teacher to check. Once approved, I'll remember it forever! 😊"
            save_chat(user_id, message, reply)
            return jsonify({"reply": reply, "known": True})
        if is_learning_interrupt(message):
            clear_teaching_state()
        else:
            reply = "Please say yes to save it, or cancel to skip 😊"
            save_chat(user_id, message, reply)
            return jsonify({"reply": reply, "known": True})

    # ── 2. Teaching flow ──────────────────────────────────────────────────────
    if pending_question:
        if is_cancel_word(normalized):
            clear_teaching_state()
            reply = "That's okay 😊"
            save_chat(user_id, message, reply)
            return jsonify({"reply": reply, "known": True})
        if is_learning_interrupt(message):
            clear_teaching_state()
        else:
            teach_match = TEACH_RE.search(message)
            proposed = (teach_match.group(1) if teach_match else message).strip()
            session["pending_question"] = pending_question
            session["pending_answer"]   = proposed
            reply = "Should I send that to my teacher to check? Say yes or cancel 😊"
            save_chat(user_id, message, reply)
            return jsonify({"reply": reply, "known": True})

    # ── 3. Extract & save memory facts ───────────────────────────────────────
    new_facts = extract_memory_from_message(message)
    for k, v in new_facts.items():
        save_memory(user_id, k, v)
        memory[k] = v

    # ── 4. Teach match against last unknown ───────────────────────────────────
    teach_match  = TEACH_RE.search(message)
    last_unknown = session.get("last_unknown_q")
    if teach_match and last_unknown:
        session["pending_question"] = last_unknown
        session["pending_answer"]   = teach_match.group(1).strip()
        reply = "Should I send that to my teacher to check? Say yes or cancel 😊"
        save_chat(user_id, message, reply)
        return jsonify({"reply": reply, "known": True})

    # ── 5. Generate response (with history-based prediction context) ──────────
    history = get_chat_history(user_id, 20)
    # Build prediction context from private chat history
    prediction_ctx = build_prediction_context(history, memory)
    result  = generate_response(message, memory, history=history, prediction_ctx=prediction_ctx)
    reply   = result["reply"]
    extras  = result.get("extras") or {}

    # ── 6. Save quiz state if a quiz was delivered ────────────────────────────
    if extras and extras.get("quiz"):
        session["active_quiz"] = extras["quiz"]
        session["quiz_subject"] = extras["quiz"].get("subject", "general")
        session.pop("waiting_for_quiz_continue", None)
    elif not extras.get("quiz") and active_quiz:
        clear_quiz_state()

    # ── 7. Log unknown teachable questions ───────────────────────────────────
    if not result["known"] and result.get("teachable"):
        add_training_item(user_id, username, message, answer=None, source="unknown")
        session["pending_question"] = message
        session.pop("pending_answer", None)
        session["last_unknown_q"]   = message

    # ── 8. Save chat ──────────────────────────────────────────────────────────
    save_chat(user_id, message, reply, extras)
    resp = {"reply": reply, "known": result["known"], "extras": extras}
    if result.get("correction_note"):
        resp["correction_note"] = result["correction_note"]
    return jsonify(resp)

@app.route("/api/history")
def history():
    if "user_id" not in session:
        return jsonify({"error": "Not logged in"}), 401
    rows = get_chat_history(session["user_id"], 60)
    return jsonify({"history": rows})

@app.route("/api/history/delete", methods=["DELETE"])
def delete_history():
    """
    Clear chat: deletes chat history AND personal memory data.
    Does NOT delete login credentials.
    """
    if "user_id" not in session:
        return jsonify({"error": "Not logged in"}), 401
    clear_user_private_data(session["user_id"])
    # Clear session states too
    session.pop("active_quiz", None)
    session.pop("waiting_for_quiz_continue", None)
    session.pop("quiz_subject", None)
    session.pop("conversation_mode", None)
    session.pop("pending_question", None)
    session.pop("pending_answer", None)
    session.pop("last_unknown_q", None)
    session.pop("last_fun_fact", None)
    return jsonify({"success": True})

@app.route("/api/me")
def me():
    if "user_id" not in session:
        return jsonify({"error": "Not logged in"}), 401
    return jsonify({
        "user":   get_user_by_id(session["user_id"]),
        "memory": get_memory(session["user_id"]),
    })

# ─── ADMIN ────────────────────────────────────────────────────────────────────
@app.route("/admin")
def admin_page():
    if "admin_id" not in session:
        return render_template("admin_login.html")
    return render_template("admin_dashboard.html",
                           admin_username=session.get("admin_username"))

@app.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    d = request.json or {}
    admin = admin_login(d.get("username", "").strip(), d.get("password", ""))
    if not admin:
        return jsonify({"success": False, "error": "Wrong admin credentials!"})
    session["admin_id"]       = admin["id"]
    session["admin_username"] = admin["username"]
    return jsonify({"success": True})

@app.route("/api/admin/logout", methods=["POST"])
def api_admin_logout():
    session.pop("admin_id", None)
    session.pop("admin_username", None)
    return jsonify({"success": True})

def _require_admin():
    return "admin_id" in session

@app.route("/api/admin/training")
def api_admin_training():
    if not _require_admin(): return jsonify({"error": "forbidden"}), 403
    status = request.args.get("status")
    return jsonify({"items": list_training(status)})

@app.route("/api/admin/training/<item_id>/approve", methods=["POST"])
def api_admin_approve(item_id):
    if not _require_admin(): return jsonify({"error": "forbidden"}), 403
    d        = request.json or {}
    answer   = d.get("answer", "").strip()
    question = d.get("question", "").strip()
    topic    = d.get("topic", "general").strip() or "general"
    keywords = d.get("keywords", "").strip()
    if not answer or not question:
        return jsonify({"success": False, "error": "Question and answer required"})
    update_training_item(item_id, status="approved",
                         answer=answer, question=question, topic=topic)
    append_to_training_csv(question, answer, topic, keywords)
    ai_brain.reload_datasets()
    return jsonify({"success": True})

@app.route("/api/admin/training/<item_id>/reject", methods=["POST"])
def api_admin_reject(item_id):
    if not _require_admin(): return jsonify({"error": "forbidden"}), 403
    update_training_item(item_id, status="rejected")
    return jsonify({"success": True})

@app.route("/api/admin/training/<item_id>", methods=["DELETE"])
def api_admin_delete(item_id):
    if not _require_admin(): return jsonify({"error": "forbidden"}), 403
    delete_training_item(item_id)
    return jsonify({"success": True})

@app.route("/api/admin/training/add", methods=["POST"])
def api_admin_add():
    if not _require_admin(): return jsonify({"error": "forbidden"}), 403
    d = request.json or {}
    q = d.get("question", "").strip()
    a = d.get("answer", "").strip()
    if not q or not a:
        return jsonify({"success": False, "error": "Question and answer required"})
    topic    = d.get("topic", "general").strip() or "general"
    keywords = d.get("keywords", "").strip()
    append_to_training_csv(q, a, topic, keywords)
    ai_brain.reload_datasets()
    return jsonify({"success": True})

@app.route("/api/admin/users")
def api_admin_users():
    if not _require_admin(): return jsonify({"error": "forbidden"}), 403
    return jsonify({"users": list_users()})

@app.route("/api/admin/export.csv")
def api_admin_export():
    if not _require_admin(): return "forbidden", 403
    path = os.path.join(os.path.dirname(__file__), "datasets", "trainning.csv")
    if not os.path.exists(path):
        buf = io.StringIO()
        csv.writer(buf).writerow(["question", "answer", "keywords", "topic"])
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=trainning.csv"})
    return send_file(path, as_attachment=True, download_name="trainning.csv")

@app.route("/api/admin/api-status")
def api_admin_api_status():
    if not _require_admin(): return jsonify({"error": "forbidden"}), 403
    from external_apis import check_all_status
    return jsonify({"apis": check_all_status()})

# ─── RUN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, port=5000)
