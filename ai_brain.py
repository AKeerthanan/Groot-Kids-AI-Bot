"""
Groot AI Brain v1.0
- TF-IDF + keyword search across all CSVs in datasets/
- Math solver (arithmetic)
- Smart memory extraction with corrections
- History-aware context
- Typo/spelling/grammar tolerance via fuzzy matching
- Content moderation: no adult/violence/offensive content
- Returns {reply, confidence, topic, known, extras?, teachable?}
"""
import os, csv, re, math, random, ast
from collections import Counter

# ── TEXT HELPERS ──────────────────────────────────────────────────────────────
def clean_text(t):
    t = t.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()

def normalize_input(t):
    t = (t or "").lower().strip().replace("'", "")
    t = re.sub(r"[^\w\s?+\-*/().]", " ", t)
    return re.sub(r"\s+", " ", t).strip()

def normalize_repeated_letters(t):
    """Handle child-like typing: 'hiiiii' -> 'hi', 'plssss' -> 'please'"""
    msg = normalize_input(t)
    msg = re.sub(r"([a-z])\1{2,}", r"\1\1", msg)
    words = msg.split()
    normalized = []
    for word in words:
        if re.fullmatch(r"h+i+",           word): normalized.append("hi")
        elif re.fullmatch(r"h+e+l+o+",     word): normalized.append("hello")
        elif re.fullmatch(r"h+e+y+",       word): normalized.append("hey")
        elif re.fullmatch(r"p+l+s+",       word): normalized.append("please")
        elif re.fullmatch(r"o+k+",         word): normalized.append("ok")
        elif re.fullmatch(r"y+e+s+",       word): normalized.append("yes")
        elif re.fullmatch(r"n+o+",         word): normalized.append("no")
        elif re.fullmatch(r"t+h+a+n+k+s*", word): normalized.append("thanks")
        else:                                       normalized.append(word)
    return " ".join(normalized)

# ── SPELLING CORRECTION (lightweight) ────────────────────────────────────────
COMMON_FIXES = {
    "wat":"what","wht":"what","wot":"what","whats":"what is",
    "hw":"how","hws":"how is","wen":"when","wer":"where","y":"why",
    "bcoz":"because","bcause":"because","cuz":"because","cos":"because",
    "pls":"please","plz":"please","thx":"thanks","thnks":"thanks",
    "ur":"your","u":"you","r":"are","b":"be","c":"see",
    "dis":"this","dat":"that","dere":"there","dey":"they","dem":"them",
    "wanna":"want to","gonna":"going to","gotta":"got to","kinda":"kind of",
    "dunno":"do not know","idk":"i do not know",
    "lol":"","lmao":"","omg":"oh my",
    "maths":"math","mathes":"math","mathmatic":"math","mathematcs":"math",
    "scienc":"science","sience":"science","sciene":"science",
    "englsh":"english","inglish":"english","engish":"english",
    "animl":"animal","animls":"animals","anmal":"animal",
    "planit":"planet","plaent":"planet","plnat":"planet",
    "photosyntesis":"photosynthesis","fotosynthesis":"photosynthesis",
    "gravitey":"gravity","graviity":"gravity","gravty":"gravity",
    "addtion":"addition","adition":"addition","additon":"addition",
    "subraction":"subtraction","subtracton":"subtraction",
    "multiplacation":"multiplication","multipication":"multiplication",
    "divison":"division",
}

def fix_spelling(text):
    words = text.lower().split()
    fixed = [COMMON_FIXES.get(w, w) for w in words]
    return " ".join(w for w in fixed if w)

def preprocess_message(message):
    """Full message normalization pipeline."""
    msg = normalize_repeated_letters(message)
    msg = fix_spelling(msg)
    return msg.strip()

def tokenize(t): return clean_text(t).split()

STOPWORDS = {
    "the","a","an","is","it","in","on","at","to","for","of","and","or","but",
    "what","how","why","when","where","who","do","does","did","i","me","my",
    "we","you","your","he","she","they","are","was","were","be","been","being",
    "have","has","had","will","would","can","could","should","may","might",
    "shall","this","that","these","those","with","from","by","about","into",
    "through","tell","give","explain","please","groot"
}

def remove_stopwords(toks): return [w for w in toks if w not in STOPWORDS]

CANCEL_WORDS = {"no","nah","nope","skip","cancel","never mind","nevermind","don't know","dont know","not sure"}
YES_WORDS    = {"yes","yeah","yep","sure","save it","confirm","ok","okay"}
QUESTION_STARTERS = {"what","why","how","who","where","when","explain"}
DOMAIN_WORDS = {
    "math","maths","english","science","grammar","reading","number","numbers",
    "addition","subtraction","multiply","division","fraction","plant","animal",
    "water","earth","space","energy","force","light","sound","sentence","word",
    "meaning","spell","history","geography","noun","nouns","verb","verbs",
    "adjective","synonym","antonym","atom","gravity","photosynthesis","planet","planets",
}
SMALLTALK_WORDS = {"good","great","nice","okay","ok","okey","fine","cool","how are you","how are you doing"}
THANKS_WORDS    = {"thanks","thank you","thankyou","thx","ty"}
HELP_INTENTS    = {"what can i do","what can you do","help","show topics","what should i ask"}
TIME_GREETINGS  = {"good morning","morning","good afternoon","afternoon","good evening","evening","good night","night"}
INVALID_NAME_VALUES = TIME_GREETINGS | {"good", "thanks", "thank you", "goodbye", "bye", "how are you"}

def is_cancel_word(msg):  return normalize_input(msg).rstrip("?") in CANCEL_WORDS
def is_yes_word(msg):     return normalize_input(msg).rstrip("?") in YES_WORDS
def is_greeting(msg):     return normalize_repeated_letters(msg).rstrip("?") in {"hi","hello","hey","sup","howdy"}
def is_smalltalk(msg):
    m = normalize_repeated_letters(msg).rstrip("?")
    return m in SMALLTALK_WORDS or m in THANKS_WORDS or m in TIME_GREETINGS
def is_help_intent(msg):  return normalize_repeated_letters(msg).rstrip("?") in HELP_INTENTS
def is_simple_smalltalk(msg):
    m = normalize_repeated_letters(msg).rstrip("?")
    return m in {"hi","hello","hey","bye","goodbye","thanks","thank you","how are you"} or is_smalltalk(m) or is_help_intent(m)

def is_gibberish(msg):
    msg = normalize_repeated_letters(msg)
    if not msg or re.search(r"\d|[+\-*/]", msg) or "?" in msg: return False
    if is_cancel_word(msg) or is_simple_smalltalk(msg): return False
    words = [w for w in re.findall(r"[a-z]+", msg) if w not in STOPWORDS]
    if not words: return False
    def randomish(w):
        if len(w) < 4 or w in DOMAIN_WORDS: return False
        vowels = sum(1 for c in w if c in "aeiou")
        unique_ratio = len(set(w)) / len(w)
        repeated = (len(w)%2==0 and w[:len(w)//2]==w[len(w)//2:]) or \
                   (len(w)%3==0 and w[:len(w)//3]*3==w)
        return vowels==0 or (len(w)-vowels)/len(w)>=0.75 or unique_ratio<=0.45 or repeated
    return all(randomish(w) for w in words)

def is_broad_sensitive_question(msg):
    patterns = [r"\breason for living\b",r"\bmeaning of life\b",r"\bpoint of life\b",
                r"\bwhy (?:am i|are we) (?:alive|living|here)\b",r"\bwhy live\b"]
    return any(re.search(p, normalize_input(msg)) for p in patterns)

def is_valid_teach_question(msg):
    msg = normalize_repeated_letters(msg)
    if not msg or is_cancel_word(msg) or is_gibberish(msg): return False
    if is_greeting(msg) or is_smalltalk(msg) or is_help_intent(msg): return False
    words = re.findall(r"[a-z]+", msg)
    if words and words[0] in QUESTION_STARTERS: return True
    if words[:2] == ["tell", "me"]: return True
    if "?" in msg: return True
    return any(w in DOMAIN_WORDS for w in words)

def cancel_reply(msg):
    m = normalize_input(msg).rstrip("?")
    if m.startswith("never") or "dont know" in m or "not sure" in m: return "That's okay 😊"
    return "Okay 😊"

# ── CONTENT MODERATION ────────────────────────────────────────────────────────
ADULT_PATTERNS = [
    r"\bsex\b",r"\bporn\b",r"\bnaked\b",r"\bnude\b",r"\bsexual\b",r"\berotic\b",
    r"\bboobs?\b",r"\bdick\b",r"\bvagina\b",r"\bpenis\b",r"\bbreast\b",
    r"\bfuck\b",r"\bshit\b",r"\bbitch\b",r"\bbastard\b",r"\bslut\b",r"\bwhore\b",
]
VIOLENCE_PATTERNS = [
    r"\bhow to (?:make|build|create) (?:a )?(?:bomb|weapon|gun|knife|poison)\b",
    r"\bhow to (?:kill|hurt|harm|attack|stab|shoot)\b",
    r"\bself[- ]harm\b",r"\bsuicid\b",r"\bcutting myself\b",
]

def check_moderation(message):
    """Returns (safe, redirect_message)."""
    msg = message.lower()
    for p in ADULT_PATTERNS:
        if re.search(p, msg):
            return False, ("🌿 Groot doesn't talk about those kinds of things! "
                          "Let's learn something amazing instead — ask me about science, "
                          "animals, or maths! 😊")
    for p in VIOLENCE_PATTERNS:
        if re.search(p, msg):
            return False, ("🌿 Groot only teaches good things! "
                          "Let's talk about something fun — ask me a science quiz, "
                          "or learn about amazing animals! 🐾")
    return True, None

# ── DATASET LOADING ───────────────────────────────────────────────────────────
DATASET = []; CORPUS = []; IDF = {}

def repair_dataset_row(row):
    if None not in row: return row
    extras = [v for v in row.get(None, []) if v is not None]
    parts = [row.get("answer",""), row.get("keywords",""), row.get("topic",""), *extras]
    if len(parts) >= 3:
        row["answer"]   = ", ".join(p.strip() for p in parts[:-2] if p is not None).strip()
        row["keywords"] = (parts[-2] or "").strip()
        row["topic"]    = (parts[-1] or "").strip()
    row.pop(None, None)
    return row

def load_all_datasets():
    global DATASET, CORPUS, IDF
    DATASET = []
    folder = os.path.join(os.path.dirname(__file__), "datasets")
    if os.path.exists(folder):
        for fn in sorted(os.listdir(folder)):
            if fn.endswith(".csv"):
                try:
                    with open(os.path.join(folder, fn), encoding="utf-8") as f:
                        for row in csv.DictReader(f):
                            row = repair_dataset_row(row)
                            safe = {(k or "").strip(): (v or "").strip() for k, v in row.items() if k is not None}
                            if safe.get("question") and safe.get("answer"):
                                DATASET.append(safe)
                except Exception as e:
                    print(f"Warning reading {fn}: {e}")
    else:
        os.makedirs(folder, exist_ok=True)
    CORPUS = [remove_stopwords(tokenize(" ".join([r.get("question",""), r.get("keywords",""), r.get("topic","")])))
              for r in DATASET]
    N = len(CORPUS) or 1
    all_words = {w for doc in CORPUS for w in doc}
    IDF = {w: math.log((N+1) / (sum(1 for d in CORPUS if w in d)+1)) + 1 for w in all_words}
    print(f"Groot loaded {len(DATASET)} training items")

def reload_datasets(): load_all_datasets()

load_all_datasets()

# ── TF-IDF ────────────────────────────────────────────────────────────────────
def tfidf_vec(tokens):
    if not tokens: return {}
    c = Counter(tokens); total = len(tokens)
    return {w: (c[w]/total) * IDF.get(w, 1) for w in c}

def cosine(v1, v2):
    common = set(v1) & set(v2)
    dot = sum(v1[w]*v2[w] for w in common)
    m1 = math.sqrt(sum(v*v for v in v1.values()))
    m2 = math.sqrt(sum(v*v for v in v2.values()))
    return dot/(m1*m2) if m1 and m2 else 0

# ── MATH SOLVER ───────────────────────────────────────────────────────────────
def try_math(message):
    msg = message.lower().replace("x","*").replace("x","*").replace("*","*").replace("/","/")
    expr = re.sub(r"[^0-9+\-*/().\s]","",msg)
    if expr.strip() and re.search(r"\d",expr) and re.search(r"[+\-*/]",expr):
        try:
            val = _safe_math_eval(expr)
            if isinstance(val, float): val = round(val, 6)
            return f"The answer is **{val}**! 🎉"
        except Exception: pass
    word_ops = {"plus":"+","add":"+","added to":"+","sum of":"+","minus":"-","subtract":"-",
                "take away":"-","times":"*","multiplied by":"*","multiply":"*","divided by":"/","divide":"/"}
    m = re.search(r"(\d+)\s*(plus|add|minus|subtract|times|multiplied by|multiply|divided by|divide)\s*(\d+)", msg)
    if m:
        a, op_w, b = int(m.group(1)), m.group(2), int(m.group(3))
        try:
            result = _safe_math_eval(f'{a}{word_ops[op_w]}{b}')
            return f"**{a} {op_w} {b} = {result}**! ⭐"
        except Exception: pass
    return None

# ── DATASET SEARCH ────────────────────────────────────────────────────────────
_MATH_OPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
}
_WORD_MATH_OPS = {
    "added to": "+", "sum of": "+", "plus": "+", "add": "+",
    "take away": "-", "minus": "-", "subtract": "-",
    "multiplied by": "*", "times": "*", "multiply": "*",
    "divided by": "/", "divide": "/",
}

def _safe_math_eval(expr):
    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if hasattr(ast, "Num") and isinstance(node, ast.Num):
            return node.n
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            val = walk(node.operand)
            return val if isinstance(node.op, ast.UAdd) else -val
        if isinstance(node, ast.BinOp) and type(node.op) in _MATH_OPS:
            left = walk(node.left)
            right = walk(node.right)
            if isinstance(node.op, ast.Div) and right == 0:
                raise ZeroDivisionError
            return _MATH_OPS[type(node.op)](left, right)
        raise ValueError

    tree = ast.parse(expr, mode="eval")
    return walk(tree)

def _extract_math_expression(message):
    text = normalize_input(message).replace("x", "*").rstrip("?")
    text = re.sub(r"^(?:what(?:\s+is|s)?|calculate|solve|answer|find)\s+", "", text).strip()
    for word, op in sorted(_WORD_MATH_OPS.items(), key=lambda item: len(item[0]), reverse=True):
        text = re.sub(rf"\b{re.escape(word)}\b", op, text)
    matches = re.findall(r"-?\d+(?:\.\d+)?(?:\s*[+\-*/]\s*-?\d+(?:\.\d+)?)+", text)
    if not matches:
        return None
    expr = matches[0].replace(" ", "")
    return expr if re.search(r"\d", expr) and re.search(r"[+\-*/]", expr) else None

def _format_math_value(value):
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{round(value, 6):g}"
    return str(value)

def try_math(message):
    expr = _extract_math_expression(message)
    if not expr:
        return None
    try:
        value = _safe_math_eval(expr)
    except Exception:
        return None
    return f"The answer is {_format_math_value(value)}! 🎉"

def dataset_query_variants(message):
    msg = normalize_repeated_letters(message).rstrip("?")
    variants = {msg}
    words = msg.split()
    for src, tgt in [("i","you"),("me","you"),("my","your")]:
        if src in words:
            variants.add(" ".join(tgt if w==src else w for w in words))
    return variants

def find_best_answer(message):
    if not DATASET: return None, None, 0
    variants = dataset_query_variants(message)
    for row in DATASET:
        if normalize_repeated_letters(row.get("question","")).rstrip("?") in variants:
            return row["answer"], row.get("topic","general"), 1.0
    for row in DATASET:
        if normalize_repeated_letters(row.get("keywords","")).rstrip("?") in variants:
            return row["answer"], row.get("topic","general"), 0.95
    tokens = remove_stopwords(tokenize(message)) or tokenize(message)
    if not tokens: return None, None, 0
    user_set = set(tokens)
    best_kw, best_kw_idx = 0, -1
    for i, row in enumerate(DATASET):
        kws = set(tokenize(row.get("keywords",""))); qts = set(tokenize(row.get("question","")))
        overlap = len(user_set & (kws | qts))
        if overlap > best_kw: best_kw, best_kw_idx = overlap, i
    user_vec = tfidf_vec(tokens)
    scores = [cosine(user_vec, tfidf_vec(d)) for d in CORPUS]
    best_tf = max(scores) if scores else 0
    best_tf_idx = scores.index(best_tf) if scores else -1
    if best_kw >= 2:    idx, conf = best_kw_idx, min(1.0, best_kw/4)
    elif best_tf>=0.18: idx, conf = best_tf_idx, best_tf
    elif best_kw==1 and best_tf>=0.1: idx, conf = best_kw_idx, 0.45
    else: return None, None, 0
    row = DATASET[idx]
    return row["answer"], row.get("topic","general"), conf

# ── MEMORY EXTRACTION ─────────────────────────────────────────────────────────
def extract_memory_from_message(message):
    memory = {}
    msg = message.lower().strip()

    # ── Name ──────────────────────────────────────────────────────────────────
    for p in [
        r"(?:no[,!.\s]+)?(?:actually[,\s]+)?my name is ([a-zA-Z]+)",
        r"(?:no[,!.\s]+)?call me ([a-zA-Z]+)",
        r"i am called ([a-zA-Z]+)",
        r"my name is ([a-zA-Z]+)",
    ]:
        m = re.search(p, msg)
        if m: memory["name"] = m.group(1).capitalize(); break

    # ── Age (must have "years old" or plain number after "i am/i'm") ──────────
    m = re.search(r"i(?:'m| am) (\d{1,2})\s*years? old", msg)
    if m: memory["age"] = m.group(1)

    # ── Grade ─────────────────────────────────────────────────────────────────
    m = re.search(r"i(?:'m| am) in (?:grade|class|year|std|standard)\s*([a-z0-9]+)", msg)
    if m: memory["grade"] = m.group(1)

    # ── City ──────────────────────────────────────────────────────────────────
    m = re.search(r"i live in ([a-zA-Z ]+?)(?:\.|!|\?|$)", msg)
    if m: memory["city"] = m.group(1).strip().title()

    # ── Pet name & type ───────────────────────────────────────────────────────
    for p in [
        r"my (?:pet|cat|dog|fish|bird|rabbit|hamster|turtle|bunny)(?:'s)?\s*(?:name\s*)?is\s+([a-zA-Z]+)",
        r"i have a (?:pet|cat|dog|fish|bird|rabbit|hamster|turtle|bunny)\s+(?:named?|called)\s+([a-zA-Z]+)",
    ]:
        m = re.search(p, msg)
        if m: memory["pet_name"] = m.group(1).capitalize(); break
    m = re.search(r"(?:i have a|my pet is a?)\s+(cat|dog|fish|bird|rabbit|hamster|turtle|parrot|snake|lizard)", msg)
    if m: memory["pet_type"] = m.group(1)

    # ── Favourite (colour, food, subject, sport, etc.) ────────────────────────
    m = re.search(r"my (?:favou?rite|fav)\s+([a-z]+)\s+is\s+([a-zA-Z0-9 ]+?)(?:\.|!|\?|$)", msg)
    if m: memory["favourite_" + m.group(1)] = m.group(2).strip().rstrip(".")

    # ── Hobby — extended to catch watching films/movies ───────────────────────
    hobby_patterns = [
        r"my hobby is (watching (?:films?|movies?|videos?|anime|tv|shows?))",
        r"my hobby is (playing [a-zA-Z ]+)",
        r"my hobby is ([a-zA-Z ]+)",
        r"i (?:like|love|enjoy)\s+(watching (?:films?|movies?|videos?|anime|tv|shows?))",
        r"i (?:like|love|enjoy|do)\s+(playing [a-zA-Z]+)",
        r"i (?:like|love|enjoy)\s+(reading|painting|drawing|dancing|coding|singing|swimming|cooking|gardening|gaming|hiking)",
    ]
    for p in hobby_patterns:
        m = re.search(p, msg)
        if m: memory["hobby"] = m.group(1).strip(); break

    # ── Generic "my X's name is Y" ────────────────────────────────────────────
    m = re.search(r"my ([a-z]+(?:'s)?) (?:name )?is ([a-zA-Z]+)", msg)
    if m:
        key = m.group(1).replace("'s","").strip()
        if key not in ("name","pet","hobby","favourite","fav"):
            memory[key+"_name"] = m.group(2).capitalize()

    return memory

# ── PERSONAL-INFO QUESTIONS ───────────────────────────────────────────────────
def answer_about_self(message, memory):
    msg = message.lower()

    # ── Saving confirmations — reply friendly when user gives personal info ───
    if re.search(r"my hobby is (.+)", msg):
        m = re.search(r"my hobby is (.+)", msg)
        hobby = m.group(1).strip().rstrip(".!?") if m else ""
        if hobby:
            return f"Got it! 🌿 I'll remember that your hobby is **{hobby}**! That's awesome! 😊"
    if re.search(r"my favou?rite colou?r is (\w+)", msg):
        m = re.search(r"my favou?rite colou?r is (\w+)", msg)
        colour = m.group(1).strip() if m else ""
        if colour:
            return f"Beautiful choice! 🌿 I'll remember that your favourite colour is **{colour}**! 😊"
    if re.search(r"my favou?rite food is (.+)", msg):
        m = re.search(r"my favou?rite food is (.+)", msg)
        food = m.group(1).strip().rstrip(".!?") if m else ""
        if food:
            return f"Yummy! 🌿 I'll remember that your favourite food is **{food}**! 😋"
    if re.search(r"my favou?rite subject is (\w+)", msg):
        m = re.search(r"my favou?rite subject is (\w+)", msg)
        subj = m.group(1).strip() if m else ""
        if subj:
            return f"Great choice! 📚🌿 I'll remember that your favourite subject is **{subj}**!"
    if re.search(r"i(?:'m| am) in (?:grade|class|year|std|standard)\s*([a-z0-9]+)", msg):
        m = re.search(r"i(?:'m| am) in (?:grade|class|year|std|standard)\s*([a-z0-9]+)", msg)
        grade = m.group(1) if m else ""
        if grade:
            return f"Got it! 📚🌿 Grade **{grade}** — I'll remember that and help you study!"
    if re.search(r"i live in ([a-zA-Z ]+?)(?:\.|!|\?|$)", msg):
        m = re.search(r"i live in ([a-zA-Z ]+?)(?:\.|!|\?|$)", msg)
        city = m.group(1).strip().title() if m else ""
        if city:
            return f"Nice! 🏠🌿 I'll remember that you live in **{city}**!"
    if re.search(r"i(?:'m| am) (\d{1,2})\s*years? old", msg):
        m = re.search(r"i(?:'m| am) (\d{1,2})\s*years? old", msg)
        age = m.group(1) if m else ""
        if age:
            return f"Got it! 🎂🌿 I'll remember that you are **{age}** years old!"
    if re.search(r"i (?:like|love|enjoy)\s+watching (?:films?|movies?)", msg):
        return "Got it! 🎬🌿 I'll remember that your hobby is **watching films**! Great taste! 😊"
    if re.search(r"i (?:like|love)\s+playing (\w+)", msg):
        m = re.search(r"i (?:like|love)\s+playing (\w+)", msg)
        sport = m.group(1) if m else "sports"
        return f"Awesome! ⚽🌿 I'll remember that you love playing **{sport}**!"
    if re.search(r"i love dancing|i like dancing|i enjoy dancing", msg):
        return "Amazing! 💃🌿 I'll remember that you love **dancing**!"

    # ── Recall questions ──────────────────────────────────────────────────────
    if re.search(r"what(?:'s| is) my name|who am i|do you (?:know|remember) my name", msg):
        name = memory.get("name")
        if name and normalize_input(name).rstrip("?") in INVALID_NAME_VALUES:
            name = None
        return f"Of course — your name is **{name}**! 🌿" if name else "I don't know your name yet! Tell me: 'My name is …' 😊"
    if re.search(r"what(?:'s| is) my pet(?:'s)? name|my pet name|what is my (?:cat|dog|bird|fish|rabbit|hamster) name", msg):
        pet = memory.get("pet_name"); ptype = memory.get("pet_type","pet")
        return f"Your {ptype}'s name is **{pet}**! 🐾🌿" if pet else "You haven't told me your pet's name yet! 😊"
    fav = re.search(r"what(?:'s| is) my favou?rite (\w+)", msg)
    if fav:
        key = "favourite_" + fav.group(1); v = memory.get(key)
        return f"Your favourite {fav.group(1)} is **{v}**! ⭐🌿" if v else f"You haven't told me your favourite {fav.group(1)} yet! Tell me 😊"
    if "how old am i" in msg or "what is my age" in msg:
        a = memory.get("age")
        return f"You're **{a}** years old! 🎂🌿" if a else "I don't know your age yet! Tell me 😊"
    if "where do i live" in msg or "what is my city" in msg:
        c = memory.get("city")
        return f"You live in **{c}**! 🏠🌿" if c else "You haven't told me where you live yet! 😊"
    if re.search(r"what is my hobby|what do i (?:like|enjoy)|what is my favourite hobby", msg):
        h = memory.get("hobby")
        return f"You told me you enjoy **{h}**! 🎨🌿" if h else "You haven't told me your hobby yet! 😊"
    if "what grade" in msg or "what class am i in" in msg:
        g = memory.get("grade")
        return f"You're in grade **{g}**! 📚" if g else "You haven't told me your grade yet!"
    gen = re.search(r"what(?:'s| is) my ([a-z]+)(?:'s)? name|who is my ([a-z]+)", msg)
    if gen:
        key = (gen.group(1) or gen.group(2) or "").strip() + "_name"
        v = memory.get(key); thing = gen.group(1) or gen.group(2)
        return f"Your {thing}'s name is **{v}**! 😊" if v else f"You haven't told me your {thing}'s name yet!"
    return None

def personalise(answer, memory):
    name = memory.get("name")
    if name and normalize_input(name).rstrip("?") in INVALID_NAME_VALUES:
        name = None
    if name and name.lower() not in answer.lower():
        greet = random.choice([
            f"Great question, {name}! 😊 ", f"Hey {name}! 😊 ",
            f"Oh {name}, I love that! 🎉 ", f"Nice one, {name}! ⭐ ",
            f"{name}, that's interesting! 💙 ",
        ])
        answer = greet + answer
    return answer

# ── HISTORY-AWARE CONTEXT ─────────────────────────────────────────────────────
def _last_topic_from_history(history):
    if not history: return None
    for h in reversed(history[-5:]):
        m = re.search(r"\*\*([^*]+)\*\*", h.get("reply",""))
        if m: return m.group(1).strip()
    return None

def _is_followup(message):
    return bool(re.search(r"\b(?:tell me more|more about|more about it|continue|next|what else|and then|also|go on)\b", message, re.I))

# ── INTENT ROUTER / EXTERNAL APIs ────────────────────────────────────────────
import external_apis as ext

_QUIZ_RE   = re.compile(r"\b(quiz|test me|ask me|trivia)\b", re.I)
_DEFINE_RE = re.compile(r"(?:define|meaning of|what does)\s+(?:the\s+word\s+)?([a-zA-Z\-]+)|what\s+is\s+the\s+meaning\s+of\s+([a-zA-Z\-]+)", re.I)
_RANDOM_IMAGE_RE = re.compile(
    r"\b(?:show me|give me|find|get)?\s*(?:a|an)?\s*"
    r"(?:random|fun|cool|surprise)?\s*(?:picture|image|photo|pic)\s*(?:please)?$",
    re.I,
)
_IMAGE_RE  = re.compile(r"(?:show me|give me|find|get)?\s*(?:a|an)?\s*(?:fun|cool|random)?\s*(?:picture|image|photo|pic)\s+(?:of|about)\s+(.+)", re.I)
_VIDEO_RE  = re.compile(r"(?:show me|give me|find|play)?\s*(?:a\s+)?(?:video|youtube)\s+(?:about|on|of)?\s*(.+)", re.I)
_BOOK_RE   = re.compile(r"\bbooks?\s+(?:about|on|for)\s+(.+)", re.I)
_ANIMAL_RE = re.compile(r"\b(random animal|tell me about an animal|animal fact|some animal)\b", re.I)
_NASA_RE   = re.compile(r"\b(astronomy picture|apod|nasa picture|space picture|picture of the day)\b", re.I)
_WIKI_RE   = re.compile(r"^(?:tell me about|who (?:is|was)|what (?:is|are|was|were))\s+(.+?)\??$", re.I)
_MATH_EXPR = re.compile(r"^[\d\s+\-*/().^x*,]+$")
_TOPIC_HINT= re.compile(r"\b(?:tell me more|more about it|continue|next)\b", re.I)

RANDOM_IMAGE_TOPICS = [
    "cute red panda",
    "rainbow over forest",
    "baby elephant playing",
    "colorful butterfly",
    "sea turtle ocean",
    "rocket launch space",
    "sunflower field",
    "penguin on ice",
    "waterfall nature",
    "dolphin jumping",
]

def _get_random_fun_image():
    topic = random.choice(RANDOM_IMAGE_TOPICS)
    result = ext.get_image(topic)
    if result:
        result["reply"] = f"🖼️ Here's a fun image for you:\n\n**{topic.title()}**"
        return result
    return {"reply": "I couldn't find a fun image right now 😊", "extras": {}}

def try_external_apis(message, memory=None, history=None):
    msg = (message or "").strip()
    if not msg: return None
    if _QUIZ_RE.search(msg):
        cat = next((k for k in ("science","english","maths","math","history","geography","animal","computer","general") if k in msg.lower()), None)
        return ext.get_quiz(cat)
    if _NASA_RE.search(msg): return ext.get_nasa_apod()
    if _ANIMAL_RE.search(msg): return ext.get_animal()
    if _RANDOM_IMAGE_RE.search(msg): return _get_random_fun_image()
    m = _IMAGE_RE.search(msg)
    if m:
        topic = m.group(1).strip().rstrip("?.! ")
        return ext.get_image(topic) or ext.get_wikipedia(topic)
    m = _VIDEO_RE.search(msg)
    if m and ("video" in msg.lower() or "youtube" in msg.lower()):
        return ext.get_youtube(m.group(1).strip().rstrip("?.! "))
    m = _BOOK_RE.search(msg)
    if m: return ext.get_books(m.group(1).strip().rstrip("?.! "))
    m = _DEFINE_RE.search(msg)
    if m:
        word = (m.group(1) or m.group(2) or "").strip()
        if word and word not in {"life","love","everything"}:
            d = ext.get_definition(word)
            if d: return d
    if _MATH_EXPR.match(msg) and re.search(r"\d", msg) and re.search(r"[+\-*/]", msg):
        ans = ext.get_math(msg)
        if ans: return ans
    if _TOPIC_HINT.search(msg) or _is_followup(msg):
        topic = _last_topic_from_history(history)
        if topic: return ext.get_wikipedia(topic)
    m = _WIKI_RE.match(msg)
    if m:
        topic = m.group(1).strip().rstrip("?.! ")
        if topic and topic.lower() not in {"your name","you","this","that","it","groot"}:
            wiki = ext.get_wikipedia(topic)
            if wiki: return wiki
            duck = ext.get_duckduckgo(topic)
            if duck: return duck
    return None

# ── FRIENDLY WRAPPER ──────────────────────────────────────────────────────────
def _friendly_wrap(reply, memory, history=None):
    name = (memory or {}).get("name")
    if name and normalize_input(name).rstrip("?") in INVALID_NAME_VALUES:
        name = None
    if name and name.lower() in reply.lower(): return reply
    intros = [f"Sure {name}! 😊", f"Here you go, {name}! ✨", f"Ooh great question, {name}! 🌟"] if name \
        else ["Sure! 😊", "Here you go! ✨", "Ooh great question! 🌟", "Okay, look at this 👇"]
    return f"{random.choice(intros)}\n\n{reply}"

GROOT_HELP = """🌿 **I am Groot! Here's what I can do:**

📚 **Learn** — Ask me about maths, science, English, history
🎯 **Quiz** — Say "quiz me" or "give me a science quiz"
🐾 **Animals** — Say "tell me an animal fact"
🚀 **Space** — Ask for "NASA picture of the day"
🖼️ **Images** — "Show me a picture of elephants"
🎬 **Videos** — "Play a video about volcanoes"
📖 **Books** — "Show books about science"
🔢 **Maths** — Ask me "2 + 2" or "what is 100 x 5"
💡 **Facts** — "Tell me about gravity" or "Who was Einstein"
🌿 **Memory** — I remember everything you tell me!

_I understand spelling mistakes too — just ask! 😊_"""

GROOT_GREETINGS = [
    "I am Groot! 🌿 Hi there! I'm your learning forest friend! Ask me about maths, science, animals, or anything you're curious about! 🌟",
    "We are Groot! 💚 Hello! I'm so happy to see you! What would you like to learn today? 🎉",
    "Groot! 🌿 Hi! I'm here to help you learn anything! Try asking me a quiz or about animals! 🐾",
]


# ── TEXTBLOB-STYLE GRAMMAR & SPELLING CORRECTION ──────────────────────────────
# Implements the same correction approach as TextBlob without requiring the library

KNOWN_CORRECTIONS = {
    "telled": "told", "goed": "went", "runned": "ran", "fighted": "fought",
    "catched": "caught", "broked": "broke", "finded": "found", "buyed": "bought",
    "thinked": "thought", "knowed": "knew", "wented": "went", "sayed": "said",
    "putted": "put", "cutted": "cut",
    "a apple": "an apple", "a orange": "an orange", "a elephant": "an elephant",
    "a umbrella": "an umbrella", "a hour": "an hour", "a honest": "an honest",
    "a egg": "an egg", "a animal": "an animal",
    "don't have no": "don't have any", "can't do nothing": "can't do anything",
}

def correct_grammar(text):
    """TextBlob-style grammar correction: fixes tense, articles, double negatives."""
    if not text or len(text) < 3:
        return text
    result = text
    for wrong, right in KNOWN_CORRECTIONS.items():
        pattern = re.compile(re.escape(wrong), re.IGNORECASE)
        result = pattern.sub(right, result)
    # Capitalize first letter
    if result and result[0].islower():
        result = result[0].upper() + result[1:]
    return result

def apply_textblob_style_correction(message):
    """
    Full correction pipeline (mirrors TextBlob's correct() approach):
    1. Spell-fix via COMMON_FIXES dict
    2. Grammar-fix via pattern rules
    3. Normalize whitespace
    Returns (corrected, was_changed)
    """
    original = message.strip()
    step1 = fix_spelling(original)
    step2 = correct_grammar(step1)
    step3 = re.sub(r"\s+", " ", step2).strip()
    was_corrected = step3.lower() != original.lower()
    return step3, was_corrected

# ── HISTORY-BASED PREDICTION CONTEXT ─────────────────────────────────────────

def build_prediction_context(history, memory):
    """
    Analyze private chat history to build personalized prediction context.
    This is used to tailor Groot's responses based on what the user
    talks about most, their learning style, and likely next interests.
    """
    if not history or len(history) < 3:
        return {}

    topic_counts = Counter()
    quiz_count = 0
    fact_count = 0
    image_count = 0
    recent_topics = []

    TOPIC_MAP = [
        (["math","number","addition","subtract","multiply","divide","fraction","calculate"], "maths"),
        (["science","plant","animal","gravity","atom","force","energy","light","photosynthesis","biology","chemistry","physics"], "science"),
        (["english","grammar","sentence","word","spell","noun","verb","adjective","synonym","antonym"], "english"),
        (["history","ancient","war","king","queen","country","empire","civilization"], "history"),
        (["space","planet","star","nasa","moon","galaxy","universe","astronomy","rocket"], "space"),
        (["animal","dog","cat","bird","fish","mammal","reptile","insect","wildlife","creature"], "animals"),
    ]

    for row in history[-30:]:
        msg = (row.get("message") or "").lower()
        extras = row.get("extras") or {}
        for keywords, topic_name in TOPIC_MAP:
            if any(kw in msg for kw in keywords):
                topic_counts[topic_name] += 1
                recent_topics.append(topic_name)
        if "quiz" in msg or "test me" in msg: quiz_count += 1
        if "tell me" in msg or "what is" in msg or "explain" in msg: fact_count += 1
        if extras.get("image"): image_count += 1

    frequent_topics = [t for t, _ in topic_counts.most_common(3)]

    if quiz_count > fact_count:
        learning_style = "quiz"
    elif image_count > 2:
        learning_style = "visual"
    else:
        learning_style = "facts"

    likely_next = frequent_topics[0] if frequent_topics else None
    if recent_topics and frequent_topics:
        last = recent_topics[-1]
        for t in frequent_topics:
            if t != last:
                likely_next = t
                break

    return {
        "frequent_topics": frequent_topics,
        "likely_next_topic": likely_next,
        "learning_style": learning_style,
        "total_messages": len(history),
    }

def get_prediction_suggestion(prediction_ctx, memory):
    """
    Build a personalized suggestion based on user's private chat history.
    Shown when Groot can't answer, to keep conversation going helpfully.
    """
    if not prediction_ctx:
        return None
    topics = prediction_ctx.get("frequent_topics", [])
    style = prediction_ctx.get("learning_style", "facts")
    name = memory.get("name", "")
    name_str = f"{name}! " if name else ""
    if not topics:
        return None
    topic = topics[0]
    if style == "quiz":
        return f"Hey {name_str}Since you love {topic}, want a quiz? Say **\"quiz me on {topic}\"**! 🎯"
    elif style == "visual":
        return f"Hey {name_str}Want to see a picture about **{topic}**? Ask **\"show me a picture of {topic}\"**! 🖼️"
    else:
        return f"Hey {name_str}You often ask about **{topic}** — want to learn something cool today? 💡"

# ── MAIN RESPONSE ENGINE ──────────────────────────────────────────────────────
def generate_response(message, memory, history=None, prediction_ctx=None):
    """Returns dict: {reply, confidence, topic, known, extras?, teachable?}"""

    # 0. Content moderation
    safe, redirect = check_moderation(message)
    if not safe:
        return {"reply": redirect, "confidence": 1.0, "topic": "moderated", "known": True}

    # Pre-process: spelling fix + normalize + TextBlob-style grammar correction
    original_msg = message
    message, was_corrected = apply_textblob_style_correction(message)
    message = normalize_repeated_letters(message)
    correction_note = None
    if was_corrected and message.lower() != original_msg.lower():
        correction_note = f"✏️ *Auto-corrected: \"{original_msg}\"*"

    # 1. Math
    math_ans = try_math(message)
    if math_ans:
        r = {"reply": personalise(math_ans, memory), "confidence":1.0, "topic":"math", "known":True}
        if correction_note: r["correction_note"] = correction_note
        return r

    # 2. Cancel
    if is_cancel_word(message):
        return {"reply": cancel_reply(message), "confidence":1.0, "topic":"cancel", "known":True}

    # 3. Groot identity
    msg_low = message.lower()
    if re.search(r"\b(who are you|what are you|your name|are you groot|groot ai)\b", msg_low):
        return {"reply": (
            "🌿 I am **Groot AI**! I'm your super smart learning forest friend! "
            "I can help you learn maths, science, English, and so much more! "
            "Say 'help' to see everything I can do! 💚"
        ), "confidence":1.0, "topic":"identity", "known":True}

    # 4. Help
    if is_help_intent(message):
        name = memory.get("name","")
        prefix = f"Hey {name}! " if name else ""
        return {"reply": prefix + GROOT_HELP, "confidence":1.0, "topic":"help", "known":True}

    # 5. Personal info from memory
    self_ans = answer_about_self(message, memory)
    if self_ans:
        return {"reply": self_ans, "confidence":1.0, "topic":"memory", "known":True}

    # 6. Sensitive
    if is_broad_sensitive_question(message):
        return {"reply": "🌿 That's a big question! People find meaning in family, learning, kindness, and helping others. Talk to a trusted adult about it too 😊",
                "confidence":1.0, "topic":"sensitive", "known":True}

    # 7. External APIs
    ext_ans = try_external_apis(message, memory, history)
    if ext_ans and ext_ans.get("reply"):
        reply = ext_ans["reply"] if (ext_ans.get("extras") or {}).get("quiz") else _friendly_wrap(ext_ans["reply"], memory, history)
        return {"reply": reply,
                "extras": ext_ans.get("extras", {}),
                "confidence":0.95, "topic":"external", "known":True}

    # 8. Dataset search
    answer, topic, conf = find_best_answer(message)
    if answer and conf > 0.3:
        reply = answer if topic in {"greeting", "smalltalk"} else personalise(answer, memory)
        r = {"reply": reply, "confidence":conf, "topic":topic, "known":True}
        if correction_note: r["correction_note"] = correction_note
        return r

    # 9. Teach Me feature — step-by-step lessons using dataset
    teach_me_m = re.search(r"teach me (?:about[\s]+)?(.+)", msg_low)
    if teach_me_m:
        topic_req = teach_me_m.group(1).strip().rstrip("?.")
        # Search dataset for all answers about this topic
        topic_rows = [r for r in DATASET if
                      topic_req in r.get("topic","").lower() or
                      topic_req in r.get("keywords","").lower() or
                      topic_req in r.get("question","").lower()]
        if topic_rows:
            name = memory.get("name","")
            greeting = f"Great choice, {name}! " if name else "Great choice! "
            lines = [f"🏫 **{greeting}Let me teach you about {topic_req.title()}!**", ""]
            for i, row in enumerate(topic_rows[:5], 1):
                lines.append(f"**{i}. {row['question']}**")
                lines.append(f"   {row['answer']}")
                lines.append("")
            lines.append("💬 Ask me any question about this, or say **quiz me** to test yourself! 🎯")
            reply = "\n".join(lines)
            r = {"reply": reply, "confidence": 0.95, "topic": topic_req, "known": True}
            if correction_note: r["correction_note"] = correction_note
            return r

    # 9b. History-aware follow-up
    if history and _is_followup(message):
        last_topic = _last_topic_from_history(history)
        if last_topic:
            wiki = ext.get_wikipedia(last_topic)
            if wiki:
                return {"reply": _friendly_wrap(wiki["reply"], memory, history),
                        "extras": wiki.get("extras",{}), "confidence":0.8, "topic":"external", "known":True}

    # 10. Gibberish
    if is_gibberish(message):
        return {"reply": "🌿 I didn't understand that! Try asking about maths, English, science, or say 'help'! 😊",
                "confidence":1.0, "topic":"gibberish", "known":True}

    # 11. Greeting / smalltalk
    if is_greeting(message) or is_smalltalk(message):
        name = memory.get("name","")
        greet = f"Hi {name}! 🌿 " if name else "🌿 "
        return {"reply": greet + random.choice(GROOT_GREETINGS),
                "confidence":0.9, "topic":"greeting", "known":True}

    # 12. Unknown educational question — invite teaching + show prediction
    if is_valid_teach_question(message):
        suggestion = get_prediction_suggestion(prediction_ctx, memory)
        base = "I don't know that yet! 🌿 Can you tell me the answer so I can learn?"
        if suggestion:
            base = base + "\n\n" + suggestion
        return {"reply": base, "confidence":0, "topic":"unknown", "known":False, "teachable":True}

    # 13. Fallback with prediction suggestion
    suggestion = get_prediction_suggestion(prediction_ctx, memory)
    fallback = "🌿 I didn't understand that! Try asking about maths, English, science, or say 'help'! 😊"
    if suggestion:
        fallback = fallback + "\n\n" + suggestion
    return {"reply": fallback, "confidence":0, "topic":"unknown", "known":True, "teachable":False}
