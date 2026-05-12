"""
external_apis.py — Groot AI external knowledge providers.
All APIs wrapped with short timeouts, graceful fallback, and latency tracking.
Zoo Animals fixed: uses correct RapidAPI endpoint.
Image description via Wikipedia/DuckDuckGo as fallback.
"""
import os, re, html, time, random, requests
from urllib.parse import quote_plus
from dotenv import load_dotenv
load_dotenv()

TIMEOUT = 8

NASA_KEY      = os.getenv("NASA_API_KEY",       "4qdlVE5RRGm0Z9qkdGg6BSHEK6B5whOuiwNQP8cq")
GOOGLE_BOOKS  = os.getenv("GOOGLE_BOOKS_KEY",   "AIzaSyBcBJQsO73e408vnQo9THKEtqZQ0GTXrdM")
RAPIDAPI_KEY  = os.getenv("RAPIDAPI_KEY",       "1e03fa2bf0msh2caf208646c94b5p123919jsn0c4d5448abbf")
NINJA_MATH    = os.getenv("API_NINJAS_KEY",     "nWF5IYaeq2tX3hTBibRHaRQ35cuUg4ztFVMsXUYa")
YOUTUBE_KEY   = os.getenv("YOUTUBE_API_KEY",    "AIzaSyAu3i5EvyVB_gwVwhMgxGrTTCbjW-JBmLc")
UNSPLASH_KEY  = os.getenv("UNSPLASH_ACCESS_KEY","tL2Mc_43GRXHptunrwUOFbKnA-FpsKqquB4lTYQp2jk")

def _get(url, **kw):
    kw.setdefault("timeout", TIMEOUT)
    r = requests.get(url, **kw)
    r.raise_for_status()
    return r

# 1. Quiz — Fixed: store correct/options for answer checking
KID_QUIZZES = {
    "science": {
        "title": "🧪 Science Quiz Time!",
        "items": [
            {"question": "What do plants need to make food?", "options": ["Sunlight", "Plastic", "Shoes", "Stones"], "correct": "Sunlight", "explanation": "Plants use sunlight to make their own food. 🌱"},
            {"question": "Which part of your body helps you see?", "options": ["Eyes", "Elbows", "Knees", "Hair"], "correct": "Eyes", "explanation": "Your eyes take in light so your brain can understand what you are looking at. 👀"},
            {"question": "What do we breathe in from the air?", "options": ["Oxygen", "Sand", "Paint", "Sugar"], "correct": "Oxygen", "explanation": "Our bodies need oxygen from the air to stay alive and full of energy."},
            {"question": "What is frozen water called?", "options": ["Ice", "Steam", "Mud", "Smoke"], "correct": "Ice", "explanation": "When water gets very cold, it freezes and becomes ice. ❄️"},
        ],
    },
    "math": {
        "title": "🔢 Math Quiz Time!",
        "items": [
            {"question": "What is 5 + 3?", "options": ["8", "6", "10", "2"], "correct": "8", "explanation": "If you count 5 and then 3 more, you land on 8."},
            {"question": "Which number comes after 9?", "options": ["10", "7", "5", "12"], "correct": "10", "explanation": "Counting goes 8, 9, 10, so 10 comes right after 9."},
            {"question": "What shape has three sides?", "options": ["Triangle", "Circle", "Square", "Rectangle"], "correct": "Triangle", "explanation": "A triangle always has three sides and three corners."},
            {"question": "What is 10 - 4?", "options": ["6", "4", "14", "8"], "correct": "6", "explanation": "Taking 4 away from 10 leaves 6."},
        ],
    },
    "english": {
        "title": "📚 English Quiz Time!",
        "items": [
            {"question": "Which word is a noun?", "options": ["Dog", "Run", "Blue", "Quickly"], "correct": "Dog", "explanation": "A noun names a person, place, thing, or animal. Dog is an animal."},
            {"question": "Which word should start a sentence?", "options": ["A capital letter", "A tiny letter", "A comma", "A full stop"], "correct": "A capital letter", "explanation": "Sentences begin with a capital letter, like 'The cat sleeps.'"},
            {"question": "Which word rhymes with cat?", "options": ["Hat", "Dog", "Sun", "Pen"], "correct": "Hat", "explanation": "Cat and hat end with the same sound, so they rhyme."},
            {"question": "Which mark ends a question?", "options": ["Question mark", "Comma", "Apostrophe", "Dash"], "correct": "Question mark", "explanation": "A question mark goes at the end of a question, like 'How are you?'"},
        ],
    },
    "general": {
        "title": "🌍 General Quiz Time!",
        "items": [
            {"question": "How many days are in one week?", "options": ["7", "5", "10", "12"], "correct": "7", "explanation": "One week has seven days, from Monday through Sunday."},
            {"question": "What color is the sky on a clear sunny day?", "options": ["Blue", "Green", "Black", "Orange"], "correct": "Blue", "explanation": "On a clear sunny day, the sky usually looks blue."},
            {"question": "Which animal says 'meow'?", "options": ["Cat", "Cow", "Duck", "Horse"], "correct": "Cat", "explanation": "Cats often make a meow sound when they want attention."},
            {"question": "What do you use to write in a notebook?", "options": ["Pencil", "Spoon", "Pillow", "Ball"], "correct": "Pencil", "explanation": "A pencil makes marks on paper and can usually be erased."},
        ],
    },
}

QUIZ_ALIASES = {
    "math": "math",
    "maths": "math",
    "english": "english",
    "science": "science",
    "general": "general",
    "history": "general",
    "geography": "general",
    "animal": "general",
    "computer": "general",
}

def get_quiz(category=None, difficulty="easy"):
    subject = QUIZ_ALIASES.get((category or "general").lower(), "general")
    pool = KID_QUIZZES[subject]
    item = random.choice(pool["items"])
    options = list(item["options"])
    correct = item["correct"]
    answer_letter = chr(65 + options.index(correct))
    opts_str = "\n".join(f"{chr(65+i)}. {o}" for i, o in enumerate(options))
    return {
        "reply": f"{pool['title']}\n\n**{item['question']}**\n\n{opts_str}\n\n_Type A, B, C, or D to answer!_",
        "extras": {
            "quiz": {
                "active": True,
                "subject": subject,
                "question": item["question"],
                "options": options,
                "answer": answer_letter,
                "correct": correct,
                "explanation": item["explanation"],
            }
        }
    }

# 2. NASA APOD
def get_nasa_apod():
    try:
        d = _get(f"https://api.nasa.gov/planetary/apod?api_key={NASA_KEY}").json()
        title = d.get("title","Astronomy Picture of the Day")
        sents = (d.get("explanation") or "").split(". ")
        short = ". ".join(sents[:3]).strip()
        if short and not short.endswith("."): short += "."
        media, is_img = d.get("hdurl") or d.get("url"), d.get("media_type") == "image"
        extras = {}
        if media and is_img: extras["image"] = media
        elif media: extras["link"] = media
        return {"reply": f"🚀 **{title}**\n\n{short}", "extras": extras}
    except Exception as e:
        print(f"NASA error: {e}")
        return None

# 3. Google Books
def get_books(query):
    try:
        d = _get(f"https://www.googleapis.com/books/v1/volumes?q={quote_plus(query)}&maxResults=3&key={GOOGLE_BOOKS}").json()
        items = d.get("items") or []
        if not items: return None
        lines, thumb = [f"📚 Here are some books about **{query}**:\n"], None
        for it in items[:3]:
            v = it.get("volumeInfo", {})
            title  = v.get("title","Untitled")
            author = ", ".join(v.get("authors") or ["Unknown"])
            desc   = (v.get("description") or "")[:140]
            lines.append(f"• **{title}** — _{author}_\n  {desc}{'…' if desc else ''}")
            if not thumb: thumb = (v.get("imageLinks") or {}).get("thumbnail")
        return {"reply": "\n\n".join(lines), "extras": {"image": thumb} if thumb else {}}
    except Exception as e:
        print(f"Books error: {e}")
        return None

# 4. Zoo Animals — Fixed with multiple endpoint fallbacks
def get_animal():
    """Try multiple Zoo/Animal APIs with fallback chain."""
    
    # Attempt 1: API Ninjas Animals (reliable free API)
    try:
        animals = ["lion","elephant","giraffe","penguin","dolphin","tiger","panda","koala",
                   "cheetah","gorilla","flamingo","jaguar","wolf","bear","eagle"]
        animal_name = random.choice(animals)
        r = _get(
            f"https://api.api-ninjas.com/v1/animals?name={animal_name}",
            headers={"X-Api-Key": NINJA_MATH}
        )
        data = r.json()
        if data and isinstance(data, list) and len(data) > 0:
            a = data[0]
            name = a.get("name", animal_name).title()
            taxonomy = a.get("taxonomy", {})
            characteristics = a.get("characteristics", {})
            locations = a.get("locations", [])
            
            diet = characteristics.get("diet", "various foods")
            habitat = characteristics.get("habitat", "various regions")
            lifespan = characteristics.get("lifespan", "unknown")
            top_speed = characteristics.get("top_speed", "")
            location_str = ", ".join(locations[:2]) if locations else "various regions"
            
            reply = f"🐾 **Did you know about the {name}?**\n\n"
            reply += f"🌍 Found in: {location_str}\n"
            reply += f"🥗 Diet: {diet}\n"
            reply += f"🏠 Habitat: {habitat}\n"
            reply += f"⏰ Lifespan: {lifespan}\n"
            if top_speed:
                reply += f"⚡ Top Speed: {top_speed}\n"
            
            # Get image from Unsplash as complement
            img_result = get_image(f"{name} animal wildlife")
            img_url = None
            if img_result and img_result.get("extras", {}).get("image"):
                img_url = img_result["extras"]["image"]
            
            return {"reply": reply, "extras": {"image": img_url} if img_url else {}}
    except Exception as e:
        print(f"API Ninjas animals error: {e}")
    
    # Attempt 2: RapidAPI Zoo Animals (original)
    try:
        headers = {
            "x-rapidapi-host": "zoo-animal-api.p.rapidapi.com",
            "x-rapidapi-key": RAPIDAPI_KEY
        }
        data = _get("https://zoo-animal-api.p.rapidapi.com/animals/rand/1", headers=headers).json()
        if data:
            a = data[0] if isinstance(data, list) else data
            name = a.get("name", "animal")
            latin = a.get("latin_name", "")
            habitat = a.get("habitat", "various places")
            diet = a.get("animal_type", "animal")
            reply = f"🐾 Did you know about the **{name}**?\n\nIt's a {diet.lower()} that lives in {habitat.lower()}."
            if latin:
                reply += f"\n_Scientific name:_ {latin}"
            img = a.get("image_link")
            return {"reply": reply, "extras": {"image": img} if img else {}}
    except Exception as e:
        print(f"RapidAPI Zoo error: {e}")
    
    # Attempt 3: Wikipedia fallback for animal fact
    try:
        animals_wiki = ["African elephant","Bengal tiger","Giant panda","Blue whale","Snow leopard"]
        animal = random.choice(animals_wiki)
        result = get_wikipedia(animal)
        if result:
            result["reply"] = "🐾 " + result["reply"]
            return result
    except Exception as e:
        print(f"Wikipedia animal fallback error: {e}")
    
    return None

# 5. Dictionary
def get_definition(word):
    word = re.sub(r"[^a-zA-Z\-]","",word).strip()
    if not word: return None
    try:
        d = _get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}").json()
        if not isinstance(d,list) or not d: return None
        m = (d[0].get("meanings") or [{}])[0]
        defs = m.get("definitions") or [{}]
        defn = defs[0].get("definition",""); example = defs[0].get("example","")
        reply = f"📖 **{word}** _({m.get('partOfSpeech','')})_\n\n👉 {defn}"
        if example: reply += f'\n\n_Example:_ "{example}"'
        return {"reply": reply}
    except Exception: return None

# 6. Math
def get_math(expression):
    expr = expression.strip()
    if not expr: return None
    try:
        r = _get(f"https://api.mathjs.org/v4/?expr={quote_plus(expr)}")
        if r.text and "Error" not in r.text:
            return {"reply": f"🧮 **{expr}** = **{r.text.strip()}** ⭐"}
    except Exception: pass
    try:
        r = _get("https://api.api-ninjas.com/v1/calculator", params={"expression": expr}, headers={"X-Api-Key": NINJA_MATH})
        d = r.json()
        if d.get("result") is not None:
            return {"reply": f"🧮 **{expr}** = **{d['result']}** ⭐"}
    except Exception: pass
    return None

# 7. Wikipedia
def get_wikipedia(topic):
    topic = (topic or "").strip().rstrip("?.! ")
    if not topic: return None
    try:
        d = _get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote_plus(topic)}", headers={"User-Agent":"GrootAI/1.0"}).json()
        if d.get("type") == "disambiguation" or not d.get("extract"): return None
        sents = re.split(r"(?<=[.!?])\s+", d["extract"])
        short = " ".join(sents[:3]).strip()
        title = d.get("title", topic)
        thumb = (d.get("thumbnail") or {}).get("source")
        return {"reply": f"💡 **{title}**\n\n{short}", "extras": {"image": thumb} if thumb else {}}
    except Exception: return None

# 8. DuckDuckGo
def get_duckduckgo(query):
    try:
        d = _get(f"https://api.duckduckgo.com/?q={quote_plus(query)}&format=json&no_html=1&skip_disambig=1").json()
        text = d.get("AbstractText") or d.get("Answer") or ""
        if not text:
            for r in (d.get("RelatedTopics") or []):
                if isinstance(r, dict) and r.get("Text"):
                    text = r["Text"]; break
        if not text: return None
        sents = re.split(r"(?<=[.!?])\s+", text)
        return {"reply": f"🔎 {' '.join(sents[:2]).strip()}"}
    except Exception: return None

# 9. YouTube
def get_youtube(query):
    try:
        url = (f"https://www.googleapis.com/youtube/v3/search"
               f"?part=snippet&maxResults=1&type=video&safeSearch=strict"
               f"&q={quote_plus(query + ' for kids')}&key={YOUTUBE_KEY}")
        d = _get(url).json()
        if d.get("error") or not d.get("items"): return None
        v = d["items"][0]
        vid_id = v["id"]["videoId"]; sn = v["snippet"]
        title = sn.get("title", query)
        thumb = (sn.get("thumbnails") or {}).get("high", {}).get("url")
        link  = f"https://www.youtube.com/watch?v={vid_id}"
        embed = f"https://www.youtube.com/embed/{vid_id}"
        return {"reply": f"🎬 Here's a great video about **{query}**:\n\n**{title}**",
                "extras": {"video": embed, "link": link, "image": thumb}}
    except Exception as e:
        print(f"YouTube error: {e}")
        return None

# 10. Unsplash
def get_image(query):
    try:
        d = _get(f"https://api.unsplash.com/search/photos?query={quote_plus(query)}&per_page=1&orientation=landscape",
                 headers={"Authorization": f"Client-ID {UNSPLASH_KEY}"}).json()
        results = d.get("results") or []
        if not results: return None
        img    = results[0]["urls"]["regular"]
        author = (results[0].get("user") or {}).get("name","Unsplash")
        alt_description = results[0].get("alt_description") or query
        return {"reply": f"🖼️ Here's a picture of **{query}**:",
                "extras": {"image": img, "credit": f"Photo by {author} on Unsplash",
                           "alt": alt_description, "query": query}}
    except Exception as e:
        print(f"Unsplash error: {e}")
        return None

# 11. Image description (for when user clicks/views an image)
def describe_image_url(image_url, original_query=None):
    """Generate a description for an image based on its context/query."""
    if original_query:
        wiki = get_wikipedia(original_query)
        if wiki and wiki.get("reply"):
            return wiki["reply"]
        ddg = get_duckduckgo(original_query)
        if ddg and ddg.get("reply"):
            return ddg["reply"]
    return f"🖼️ This is an image of **{original_query or 'the topic'}**. It was fetched from our image library to illustrate the topic visually!"

# Admin status check
def _ping(name, fn):
    start = time.time()
    try:
        ok = fn() is not None
    except Exception:
        ok = False
    ms = int((time.time() - start) * 1000)
    return {"name": name, "ok": ok, "latency_ms": ms}

def check_all_status():
    return [
        _ping("Open Trivia DB (Quiz)",   lambda: get_quiz("general")),
        _ping("NASA APOD",               lambda: get_nasa_apod()),
        _ping("Google Books",            lambda: get_books("science")),
        _ping("API Ninjas Animals",      lambda: get_animal()),
        _ping("Free Dictionary",         lambda: get_definition("hello")),
        _ping("Math.js / API Ninjas",    lambda: get_math("2+2")),
        _ping("Wikipedia",               lambda: get_wikipedia("Earth")),
        _ping("DuckDuckGo",              lambda: get_duckduckgo("gravity")),
        _ping("YouTube Data API",        lambda: get_youtube("addition")),
        _ping("Unsplash Images",         lambda: get_image("cat")),
    ]
