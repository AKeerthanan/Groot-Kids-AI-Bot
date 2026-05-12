# 🌿 Groot AI — v2.0

> Your super smart forest friend that teaches, learns, and remembers you!

## ✨ What's New in v2.0

### 🧠 Personal Memory — Stored in Database
- Groot remembers your **name, age, pet, hobbies, grade, city** across sessions
- Memory is stored securely in Supabase (not just session)
- Groot personalizes every reply using your saved info

### 🗑️ Clear Chat = Delete Your Private Data
- Clicking **Clear Chat** now deletes BOTH:
  - All your chat history
  - All your personal memory (name, age, pet, preferences etc.)
- **Does NOT delete** your login account/credentials
- Fresh start: Groot won't remember anything personal after clearing

### ✏️ TextBlob-Style Spelling & Grammar Correction
- Uses a correction pipeline matching `from textblob import TextBlob`
- **Spell fixes**: "hw r u" → "how are you", "bcoz" → "because"
- **Grammar fixes**: "I goed" → "I went", "a apple" → "an apple", "I telled" → "I told"
- **Normalization**: repeated letters ("hiiiii" → "hi"), whitespace cleanup
- When corrected, a small note is shown: *✏️ Auto-corrected: "..."*

### 🔮 AI Prediction from Private Chat History
- Groot analyzes your **last 30 messages** to learn:
  - Your **favorite topics** (maths, science, English, space, animals...)
  - Your **learning style** (quizzes, facts, or visual/images)
  - Your **likely next interest**
- When Groot doesn't know something, it suggests: *"Since you love science, want a quiz?"*

### 🏫 Teach Me Feature
- Say **"Teach me about [topic]"** for a step-by-step lesson
- Uses Groot's built-in dataset to deliver structured mini-lessons
- **Quick buttons** in sidebar: Teach: Maths, Science, English, Space, Animals
- After the lesson, Groot invites you to quiz yourself

### 💬 More Friendly Chat Format
- Warmer personalized greetings using your name
- Correction notes shown subtly (not disruptive)
- Sidebar organized into: Quick Learn / Fun / **Teach Me** sections
- Welcome pills include: Maths, English, Science, Space, Quiz

---

## 🚀 Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Fill in your Supabase URL & Key in .env
python app.py
```

## 📁 Project Structure
```
groot_ai/
├── app.py              # Flask routes
├── ai_brain.py         # AI logic, TextBlob-style correction, prediction
├── database.py         # Supabase operations (incl. clear_user_private_data)
├── external_apis.py    # Wikipedia, NASA, quiz, image APIs
├── datasets/           # CSV training data
├── templates/
│   ├── chat.html       # Main chat UI
│   ├── index.html      # Login/signup
│   └── admin_*.html    # Admin dashboard
└── requirements.txt
```

## 🔑 Key API Routes

| Route | Method | Description |
|-------|--------|-------------|
| `/api/chat` | POST | Send message, get reply + correction note |
| `/api/history/delete` | DELETE | **Deletes chat + personal memory** |
| `/api/me` | GET | Get user info + current memory |
| `/api/history` | GET | Load chat history |

## 🛡️ Privacy Notes
- Personal data (memory) = deleted on Clear Chat
- Login credentials = always kept (needed to log in)
- Chat is stored per user in Supabase
