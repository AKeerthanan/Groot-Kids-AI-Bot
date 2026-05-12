import os, csv, hashlib, json
from datetime import datetime
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
supabase = create_client(
    os.getenv("SUPABASE_URL", ""),
    os.getenv("SUPABASE_KEY", "")
)

def hash_password(p):
    return hashlib.sha256(p.encode()).hexdigest()

# ── USER AUTH ──────────────────────────────────────────────────────────────────
def signup_user(username, email, password, age=8):
    if supabase.table("users").select("id").eq("email", email).execute().data:
        return None, "This email is already registered! Try logging in. 😊"
    if supabase.table("users").select("id").eq("username", username).execute().data:
        return None, "This username is taken! Try a different one. 🌟"
    res = supabase.table("users").insert({
        "username": username, "email": email,
        "password_hash": hash_password(password), "age": age
    }).execute()
    return (res.data[0], None) if res.data else (None, "Something went wrong.")

def login_user(email, password):
    res = supabase.table("users").select("*") \
        .eq("email", email).eq("password_hash", hash_password(password)).execute()
    return (res.data[0], None) if res.data else (None, "Wrong email or password! 🔑")

def get_user_by_id(user_id):
    res = supabase.table("users") \
        .select("id,username,email,age,created_at") \
        .eq("id", user_id).execute()
    return res.data[0] if res.data else None

# ── MEMORY ─────────────────────────────────────────────────────────────────────
def save_memory(user_id, key, value):
    existing = supabase.table("user_memory").select("id") \
        .eq("user_id", user_id).eq("key", key).execute()
    if existing.data:
        supabase.table("user_memory").update({
            "value": value,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", existing.data[0]["id"]).execute()
    else:
        supabase.table("user_memory").insert({
            "user_id": user_id, "key": key, "value": value
        }).execute()

def get_memory(user_id) -> dict:
    res = supabase.table("user_memory").select("key,value") \
        .eq("user_id", user_id).execute()
    return {r["key"]: r["value"] for r in res.data}

def delete_user_memory(user_id):
    """Delete all personal memory/preferences for a user (NOT login details)."""
    try:
        supabase.table("user_memory").delete().eq("user_id", user_id).execute()
    except Exception as e:
        print(f"delete_user_memory error: {e}")

# ── CHAT HISTORY ───────────────────────────────────────────────────────────────
def save_chat(user_id, message, reply, extras=None):
    extras = extras or {}
    row = {"user_id": user_id, "message": message, "reply": reply}
    if extras.get("image"):    row["image_url"]  = extras["image"]
    if extras.get("video"):    row["video_url"]  = extras["video"]
    if extras.get("link"):     row["link_url"]   = extras["link"]
    other = {k: v for k, v in extras.items() if k not in ("image", "video", "link")}
    if other:
        row["extra_data"] = json.dumps(other)
    try:
        supabase.table("chat_history").insert(row).execute()
    except Exception:
        try:
            supabase.table("chat_history").insert({"user_id": user_id, "message": message, "reply": reply}).execute()
        except Exception as e2:
            print(f"save_chat error: {e2}")

def get_chat_history(user_id, limit=60):
    try:
        res = supabase.table("chat_history") \
            .select("message,reply,image_url,video_url,link_url,extra_data,created_at") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .limit(limit).execute()
    except Exception:
        try:
            res = supabase.table("chat_history") \
                .select("message,reply,created_at") \
                .eq("user_id", user_id) \
                .order("created_at", desc=True) \
                .limit(limit).execute()
        except Exception as e2:
            print(f"get_chat_history error: {e2}")
            return []
    rows = list(reversed(res.data or []))
    for r in rows:
        extras = {}
        if r.get("image_url"): extras["image"] = r["image_url"]
        if r.get("video_url"): extras["video"] = r["video_url"]
        if r.get("link_url"):  extras["link"]  = r["link_url"]
        if r.get("extra_data"):
            try:
                extras.update(json.loads(r["extra_data"]))
            except Exception:
                pass
        r["extras"] = extras
    return rows

def delete_all_chat_history(user_id):
    """Delete all chat history for a user."""
    try:
        supabase.table("chat_history").delete().eq("user_id", user_id).execute()
    except Exception as e:
        print(f"delete_all_chat_history error: {e}")

def clear_user_private_data(user_id):
    """
    Called when user clicks 'Clear Chat'.
    Deletes:
      - All chat history
      - All personal memory (name, age, pet, hobbies etc.)
    Does NOT delete:
      - Login credentials (users table)
      - Training queue items
    """
    delete_all_chat_history(user_id)
    delete_user_memory(user_id)

# ── TRAINING QUEUE ─────────────────────────────────────────────────────────────
def add_training_item(user_id, username, question, answer=None, topic="general", source="unknown"):
    supabase.table("training_queue").insert({
        "user_id": user_id, "username": username, "question": question,
        "answer": answer, "topic": topic, "source": source, "status": "pending",
    }).execute()

def list_training(status=None):
    q = supabase.table("training_queue").select("*").order("created_at", desc=True)
    if status:
        q = q.eq("status", status)
    return q.execute().data

def update_training_item(item_id, **fields):
    fields["reviewed_at"] = datetime.utcnow().isoformat()
    supabase.table("training_queue").update(fields).eq("id", item_id).execute()

def delete_training_item(item_id):
    supabase.table("training_queue").delete().eq("id", item_id).execute()

TRAINING_CSV = os.path.join(os.path.dirname(__file__), "datasets", "trainning.csv")

def append_to_training_csv(question, answer, topic="general", keywords=""):
    new_file = not os.path.exists(TRAINING_CSV)
    os.makedirs(os.path.dirname(TRAINING_CSV), exist_ok=True)
    with open(TRAINING_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["question", "answer", "keywords", "topic"])
        w.writerow([question, answer, keywords or question.lower(), topic])

# ── ADMIN ──────────────────────────────────────────────────────────────────────
def admin_login(username, password):
    res = supabase.table("admins").select("*") \
        .eq("username", username) \
        .eq("password_hash", hash_password(password)).execute()
    return res.data[0] if res.data else None

def list_users():
    res = supabase.table("users") \
        .select("id,username,email,age,created_at") \
        .order("created_at", desc=True).execute()
    return res.data
