from flask import Flask, request, jsonify, session, render_template, redirect, url_for, Response, send_file
from flask_cors import CORS
from dotenv import load_dotenv
import os, csv, io, re

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

def clear_quiz_state():
    session.pop("active_quiz", None)
    session.pop("waiting_for_quiz_continue", None)

def clear_all_quiz_state():
    clear_quiz_state()
    session.pop("quiz_subject", None)

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

    # ── 0. Quiz answer check ──────────────────────────────────────────────────
    if active_quiz:
        quiz_reply = check_quiz_answer(message, active_quiz)
        if quiz_reply:
            save_chat(user_id, message, quiz_reply)
            return jsonify({"reply": quiz_reply, "known": True})

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
    session.pop("pending_question", None)
    session.pop("pending_answer", None)
    session.pop("last_unknown_q", None)
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
