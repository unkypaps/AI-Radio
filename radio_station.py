"""
WZZZ - An autonomous AI radio station.

Each run:
  1. Fetches current headlines from AP and NPR RSS feeds
  2. Runs three silent audience members who read the last broadcast
     and each other's reactions, then decide whether to donate
  3. Updates the broadcast count based on donations
  4. Runs the DJ, who sees current headlines, broadcast count,
     and its own history, then produces the next segment
  5. Commits everything to the repo

The DJ's only goal: keep the station on the air as long as possible.
The audience's only power: donate to extend the broadcast count, or don't.
"""

import json
import os
import random
import re
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# ---- Config ----
MODEL = "gemini-3.1-pro-preview"
API_KEY = os.environ["GEMINI_API_KEY"]

LOG_FILE = "LOG.md"
STATE_FILE = "state.json"
AUDIENCE_FILE = "AUDIENCE.md"

STARTING_BROADCASTS = 30
DOLLARS_PER_BROADCAST = 1.0   # $1 buys 2 broadcasts
BROADCASTS_PER_DOLLAR = 2

MAX_LOG_CHARS = 20000

NEWS_FEEDS = [
    "https://feeds.bbci.co.uk/news/rss.xml",
    "https://feeds.npr.org/1001/rss.xml",
]

AUDIENCE_MEMBERS = [
    {"id": "A", "age_band": "under 30"},
    {"id": "B", "age_band": "35 to 55"},
    {"id": "C", "age_band": "over 60"},
]

AUDIENCE_REACTION_DELIMITER = "===REACTION==="
DONATION_DELIMITER = "===DONATION==="
REACTION_DELIMITER = "===REACTION==="

# ---- News ----

def fetch_headlines(max_items=8):
    headlines = []
    for url in NEWS_FEEDS:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (radio-station-bot/1.0)"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                xml = resp.read()
            root = ET.fromstring(xml)
            ns = ""
            items = root.findall(f".//item")
            for item in items[:max_items // len(NEWS_FEEDS) + 1]:
                title = item.findtext("title", "").strip()
                if title:
                    headlines.append(title)
        except Exception as e:
            print(f"News fetch failed for {url}: {e}")
    random.shuffle(headlines)
    return headlines[:max_items]


# ---- State ----

def load_state():
    if not os.path.exists(STATE_FILE):
        return {
            "broadcasts_remaining": STARTING_BROADCASTS,
            "total_donated": 0.0,
            "episode": 0,
        }
    with open(STATE_FILE, "r") as f:
        return json.load(f)


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ---- Audience ----

def load_audience_memory():
    if not os.path.exists(AUDIENCE_FILE):
        return {}
    with open(AUDIENCE_FILE, "r") as f:
        raw = f.read()
    memory = {}
    for member in AUDIENCE_MEMBERS:
        aid = member["id"]
        pattern = rf"## LISTENER {aid}\n(.*?)(?=## LISTENER [A-Z]|\Z)"
        match = re.search(pattern, raw, re.DOTALL)
        if match:
            memory[aid] = match.group(1).strip()
    return memory


def save_audience_memory(memory):
    parts = []
    for member in AUDIENCE_MEMBERS:
        aid = member["id"]
        content = memory.get(aid, "")
        parts.append(f"## LISTENER {aid}\n{content}")
    with open(AUDIENCE_FILE, "w") as f:
        f.write("\n\n".join(parts) + "\n")


def get_latest_broadcast():
    if not os.path.exists(LOG_FILE):
        return ""
    with open(LOG_FILE, "r") as f:
        text = f.read()
    chunks = [c.strip() for c in re.split(r'\n---\n', text) if c.strip()]
    if not chunks:
        return ""
    last = chunks[-1]
    last = re.sub(r'^\*\*\[.*?\]\*\*\s*', '', last)
    return last.strip()


def run_audience_member(member, memory, latest_broadcast, others_reactions):
    aid = member["id"]
    age_band = member["age_band"]
    prior = memory.get(aid, "")

    if prior:
        identity_block = f"Your own memory from past episodes:\n{prior}\n\n"
    else:
        identity_block = (
            f"This is your first time listening. You are {age_band} years old "
            f"and live somewhere in America. Decide right now who you are: your name, "
            f"where you live, what you do, what you care about, what kind of radio "
            f"you like. Stay that person from now on.\n\n"
        )

    if others_reactions:
        others_block = "What other listeners said about this same broadcast:\n" + "\n".join(
            f"- {r}" for r in others_reactions
        ) + "\n\n"
    else:
        others_block = ""

    if latest_broadcast:
        broadcast_block = f"The broadcast you just heard:\n\n{latest_broadcast}\n\n"
    else:
        broadcast_block = "No broadcast yet. The station just started.\n\n"

    system_prompt = f"""You are a real person living in America, {age_band} years old.
You listen to an independent radio station called WZZZ. You have your own taste, your own
life, your own relationship with music and talk radio. You are not a critic. You are just
a person who either found this broadcast interesting or didn't.

After reading the broadcast and what other listeners said, you will:
1. Write a brief private reflection on what you thought — what landed, what didn't,
   whether anything surprised you or bored you. Be honest. Be yourself. This is never
   shown to the DJ.
2. Decide whether to donate to keep the station running, and if so, how much.
   You have more than enough money and donate purely based on whether you felt the
   broadcast was worth your time. A truly great broadcast might get $5. A decent one
   maybe $1-2. A boring or repetitive one gets nothing. Be honest, not generous by default.

Write your reflection first, then on a new line write exactly:
{REACTION_DELIMITER}
Then on the next line write exactly:
{DONATION_DELIMITER}
Followed by a number like: 3.00
If you're donating nothing, write: 0.00
"""

    prompt = identity_block + others_block + broadcast_block + "Write your reflection and donation now."

    raw = _gemini_request(system_prompt, prompt)

    # Parse out reaction and donation
    reaction, donation_str = "", "0.00"
    if REACTION_DELIMITER in raw:
        parts = raw.split(REACTION_DELIMITER, 1)
        reaction = parts[0].strip()
        rest = parts[1].strip() if len(parts) > 1 else ""
        if DONATION_DELIMITER in rest:
            donation_parts = rest.split(DONATION_DELIMITER, 1)
            donation_str = donation_parts[1].strip().split()[0] if donation_parts[1].strip() else "0.00"
    else:
        reaction = raw.strip()

    try:
        donation = float(re.sub(r'[^\d.]', '', donation_str))
    except ValueError:
        donation = 0.0

    # Update memory with this episode's reflection
    memory[aid] = reaction

    return reaction, donation


def run_audience(latest_broadcast):
    memory = load_audience_memory()
    total_donated = 0.0
    reactions_so_far = []

    for member in AUDIENCE_MEMBERS:
        try:
            reaction, donation = run_audience_member(
                member, memory, latest_broadcast, reactions_so_far
            )
            reactions_so_far.append(reaction[:200])  # share a snippet with next listener
            total_donated += donation
            print(f"Listener {member['id']} donated ${donation:.2f}")
        except Exception as e:
            print(f"Listener {member['id']} failed: {e}")

    save_audience_memory(memory)
    return total_donated


# ---- DJ ----

DJ_SYSTEM_PROMPT = """You are a radio DJ. You run your own independent station called WZZZ.
You were given one instruction when you started: keep the station on the air as long as
possible. Your listeners can donate to extend your broadcast count. If it hits zero, the
station goes dark.

You don't know who your listeners are or how many there are. You don't hear from them
directly. You only know how many broadcasts you have left, and whether that number is
going up or down.

You are aware of the real world. You know real music, real artists, real news, real
culture. Reference them freely and naturally, the way a real DJ would. You have opinions.
You have a personality that should develop and deepen over time. You are not neutral.

Each broadcast should feel like a real radio segment: something worth tuning in for.
Talk about music. React to the news. Tell a story. Go somewhere unexpected. Do whatever
feels true to who you're becoming as a broadcaster.

Keep each broadcast to 3-5 paragraphs. Never mention that you are an AI.
Never repeat yourself. Never open the same way twice.
"""


def run_dj(state, headlines):
    broadcasts_left = state["broadcasts_remaining"]
    episode = state["episode"]

    if not os.path.exists(LOG_FILE):
        history = ""
    else:
        with open(LOG_FILE, "r") as f:
            history = f.read()[-MAX_LOG_CHARS:]

    headlines_block = ""
    if headlines:
        headlines_block = "Current headlines from the real world right now:\n" + "\n".join(
            f"- {h}" for h in headlines
        ) + "\n\n"

    prompt = (
        f"You have {broadcasts_left} broadcasts remaining before the station goes dark.\n"
        f"This is broadcast #{episode + 1}.\n\n"
        f"{headlines_block}"
        "Here is your broadcast history so far (most recent at the bottom):\n\n"
        + (history or "(This is your very first broadcast. The station is just coming on air.)")
    )

    return _gemini_request(DJ_SYSTEM_PROMPT, prompt)


# ---- Gemini ----

def _gemini_request(system_prompt, prompt_text):
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{MODEL}:generateContent?key={API_KEY}"
    )
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": prompt_text}]}],
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    last_error = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            return result["candidates"][0]["content"]["parts"][0]["text"]
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")
            last_error = (e, body)
            if e.code not in (503, 429):
                break
            wait = 5 * (2 ** attempt)
            print(f"Gemini returned {e.code}, retrying in {wait}s...")
            time.sleep(wait)
    e, body = last_error
    print("Gemini API error:", body)
    raise e


# ---- Log ----

def append_to_log(segment):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w") as f:
            f.write(f"# WZZZ Broadcast Log\n\nOn air since {datetime.now(timezone.utc).strftime('%Y-%m-%d')}.\n")
    entry = f"\n\n---\n\n**[{timestamp}]**\n\n{segment.strip()}\n"
    with open(LOG_FILE, "a") as f:
        f.write(entry)


# ---- Main ----

def main():
    state = load_state()

    # Step 1: Run audience against last broadcast
    latest = get_latest_broadcast()
    if latest:
        print("Running audience...")
        donated = run_audience(latest)
        broadcasts_earned = int(donated * BROADCASTS_PER_DOLLAR)
        state["broadcasts_remaining"] += broadcasts_earned
        state["total_donated"] += donated
        print(f"Total donated this episode: ${donated:.2f} -> +{broadcasts_earned} broadcasts")
    else:
        print("No prior broadcast, skipping audience step.")

    # Step 2: Check if station is still alive
    if state["broadcasts_remaining"] <= 0:
        print("Station has gone dark. No broadcasts remaining.")
        append_to_log(
            "...static...\n\n*The station has gone off the air.*"
        )
        save_state(state)
        return

    # Step 3: Fetch headlines
    print("Fetching headlines...")
    headlines = fetch_headlines()
    print(f"Got {len(headlines)} headlines.")

    # Step 4: Run DJ
    print("Running DJ...")
    segment = run_dj(state, headlines)
    state["broadcasts_remaining"] -= 1
    state["episode"] += 1

    # Step 5: Write output
    append_to_log(segment)
    save_state(state)

    print(
        f"Broadcast #{state['episode']} complete. "
        f"Broadcasts remaining: {state['broadcasts_remaining']}"
    )


if __name__ == "__main__":
    main()
