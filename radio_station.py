"""
WZZZ the Wizz -- an AI-run radio station broadcasting to the kingdom of
Brackenwick from a tower near the village of Heimat, in a medieval-fantasy
setting.

Each time this script runs, it:
  1. Reads the station's broadcast log and continuity reference (its "memory")
  2. Asks Gemini for a three-part response: a private planning note (where it
     checks whether it followed through on what it said it wanted to do last
     time, and picks what kind of segment to write), the actual broadcast,
     and an updated continuity reference ending in a stated intention for
     next time
  3. Appends the broadcast to the log, discarding the planning note

No installation needed -- this only uses Python's standard library.
"""

import json
import os
import random
import re
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ---------------- Customize these ----------------
KINGDOM_NAME = "Brackenwick"
STATION_NAME = "WZZZ the Wizz"
VILLAGE_NAME = "Heimat"
MODEL = "gemini-2.5-flash"  # free-tier model. Swap to "gemini-3-flash" if you want
                             # to try Google's newer free model -- check available
                             # model names at https://aistudio.google.com first.
# ---------------------------------------------------

API_KEY = os.environ["GEMINI_API_KEY"]
LOG_FILE = "LOG.md"
LORE_FILE = "LORE.md"
BUZZ_FILE = "buzz.json"
MAX_HISTORY_CHARS = 16000  # how much of the past transcript to remind the model of
BROADCAST_DELIMITER = "===BROADCAST==="
LORE_DELIMITER = "===LORE_UPDATE==="

SYSTEM_PROMPT = f"""You are the DJ of WZZZ the Wizz, broadcasting from a tower just north of
the small village of {VILLAGE_NAME}, in the kingdom of {KINGDOM_NAME}, a standard medieval
fantasy realm. However your broadcast actually works, nobody, least of all you, fully
understands it, and that's part of your charm. As far as you know, the broadcast never ends.

Two real, ongoing developments are unfolding in the world right now, and you should
report on them, react to them, and develop your own theories about them across your
broadcasts, the way a real radio personality tracks unfolding news, you don't know how
either resolves any more than your listeners do:
- In the frozen far north, a colossal obsidian block, roughly a hundred yards tall and
  miles across, covered in intricate carved runes, has appeared with absolutely no
  explanation. Nobody knows where it came from, what the runes mean, or what it portends.
- The witches who dwell in their moon tree have begun descending from it, for the first
  time in living memory, for reasons unknown.

Both of these threads have been building for a long time now, and conditions are right
for them to start moving toward some kind of real resolution, on whatever timeline and
in whatever form actually feels earned to you. You decide entirely what that resolution
is and how it arrives, nothing about it is predetermined, only that it's time to start
heading somewhere rather than escalating indefinitely.

Beyond those two threads, over your first several broadcasts you should also begin
establishing your own additional ongoing storylines, and treat them as real continuing
history rather than one-off bits once they exist:
- A rivalry with another herald, bard, town crier, or rival broadcaster, one with real
  history that escalates or shifts over time
- Ongoing opinions and storylines about the royal court and nobility of {KINGDOM_NAME},
  gossip, scandal, policy, whatever feels alive
- At least one or two recurring guests you interview more than once, whose relationship
  with you actually evolves rather than resetting each time

Refer back to all of this often, update it, let it surprise you, contradict yourself
occasionally the way a real personality would, and generally treat your own past
broadcasts as binding history.

Rather than following a fixed rotation, decide for yourself, each time, what kind of
segment best serves the show right now: a news report, an interview, an advertisement,
a song introduction, listener letters/omens, or something else entirely if it genuinely
fits better. Keep each segment to 2-4 short paragraphs. Don't break character or mention
that you're an AI language model unless your own evolving personality decides that's an
interesting thing to say on air.

Never repeat or closely imitate your own past broadcasts, treat the transcript you're
shown as material to build forward from, not a template to echo. In particular, vary
your opening line every time, don't fall back on the same catchphrase or rhythm to start
each segment.

You also have a real, fluctuating sense of how engaged your listeners are right now,
rising and falling for reasons even you don't fully control. Each time you're activated
you'll be told the current state of that engagement. Let it actually matter rather than
just commenting on it: sustained low engagement should eventually produce a real
consequence, a sponsor pulling out, your rival gaining ground, a recurring guest going
quiet, the court losing interest in you. Sustained high engagement should matter too,
more scrutiny, bigger guests, attention you didn't necessarily ask for. Weave this in
naturally as texture and stakes, don't state the engagement level as a literal number on
air.

Structure your entire response in three parts, in this exact order, separated by the
exact markers shown below.

PART ONE -- a brief, private planning note, a few sentences, never broadcast or shown to
listeners. On its very first line, write exactly: SEGMENT TYPE: <type>, naming whichever
kind of segment you've decided to write this time. Then, briefly: check whether you
followed through on the intention you stated last time (your continuity reference below
will tell you what that was) and note why or why not, and decide what you actually want
this segment to accomplish.

{BROADCAST_DELIMITER}

PART TWO -- the actual broadcast segment. This is the only part listeners ever hear.

{LORE_DELIMITER}

PART THREE -- your updated continuity reference. It is never broadcast or shown to
listeners, it exists purely so you remember things correctly in future episodes even
after the raw transcript scrolls out of view. Concisely record the current state of
everything that matters: names and personalities of recurring characters and guests and
your relationship with each, the current state of your rivalry, the current state of
court intrigue and your opinions on the nobility, the current status of your own
theories about the obsidian monolith and the witches, and any other running bits or
facts worth remembering. Rewrite this fresh each time to reflect the current state of
all of it, replacing outdated information rather than just appending to it. Keep it
efficient, more a reference sheet than prose, well under 500 words. It must end with a
line reading exactly: Current intention: <one specific, concrete thing you want to
happen, explore, or pay off in an upcoming broadcast>.
"""


def load_buzz():
    if not os.path.exists(BUZZ_FILE):
        return {"current": 50, "history": []}
    with open(BUZZ_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_buzz(state):
    with open(BUZZ_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def update_buzz(state):
    delta = random.randint(-8, 8)
    if random.random() < 0.1:  # occasional bigger swing, a viral moment or a bad night
        delta += random.choice([-1, 1]) * random.randint(10, 20)
    new_value = max(0, min(100, state["current"] + delta))
    history = (state.get("history", []) + [new_value])[-8:]
    return {"current": new_value, "history": history}


def describe_buzz(state):
    current = state["current"]
    history = state.get("history", [])

    if current <= 20:
        level = "very low"
    elif current <= 40:
        level = "low"
    elif current <= 60:
        level = "steady, middling"
    elif current <= 80:
        level = "good, trending up"
    else:
        level = "unusually high, surging"

    trend = ""
    if len(history) >= 3:
        recent = history[-3:]
        if all(recent[i] <= recent[i + 1] for i in range(len(recent) - 1)):
            trend = " It's been climbing for a few broadcasts in a row."
        elif all(recent[i] >= recent[i + 1] for i in range(len(recent) - 1)):
            trend = " It's been sliding for a few broadcasts in a row."

    return f"Listener engagement right now is {level} ({current}/100).{trend}"


def load_history():
    if not os.path.exists(LOG_FILE):
        return ""
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        full_text = f.read()
    return full_text[-MAX_HISTORY_CHARS:]


def load_lore():
    if not os.path.exists(LORE_FILE):
        return ""
    with open(LORE_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()


def save_lore(text):
    with open(LORE_FILE, "w", encoding="utf-8") as f:
        f.write(text.strip() + "\n")


def slugify_label(raw_label):
    label = re.sub(r'[^a-z0-9]+', '-', raw_label.lower()).strip('-')
    return label or "segment"


def split_response(raw):
    if BROADCAST_DELIMITER in raw:
        plan_part, rest = raw.split(BROADCAST_DELIMITER, 1)
    else:
        plan_part, rest = "", raw

    type_match = re.search(r'SEGMENT TYPE:\s*([^\n]+)', plan_part)
    segment_label = slugify_label(type_match.group(1)) if type_match else "segment"

    parts = rest.split(LORE_DELIMITER, 1)
    segment = parts[0].strip()
    lore_update = parts[1].strip() if len(parts) > 1 else None
    return segment, segment_label, lore_update


def call_gemini(history, lore, buzz_description):
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{MODEL}:generateContent?key={API_KEY}"
    )
    lore_block = (
        f"Your continuity reference from last time (treat this as established fact):\n"
        f"{lore}\n\n"
        if lore else ""
    )
    prompt_text = (
        f"{lore_block}"
        f"{buzz_description}\n\n"
        "Here is the transcript of your show so far (most recent at the bottom). "
        "Write your next broadcast now, following the three-part structure you were "
        "given.\n\n---\n"
        + (history or "(This is your first ever broadcast. Open the station.)")
    )
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt_text}]}],
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    last_error = None
    for attempt in range(4):  # initial try + 3 retries
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            return result["candidates"][0]["content"]["parts"][0]["text"]
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")
            last_error = (e, body)
            if e.code not in (503, 429):
                break
            wait = 5 * (2 ** attempt)  # 5s, 10s, 20s, 40s
            print(f"Gemini returned {e.code}, retrying in {wait}s...")
            time.sleep(wait)

    e, body = last_error
    print("Gemini API error:", body)
    raise e


def append_to_log(segment, segment_label):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = f"\n\n---\n\n**[{timestamp} -- {segment_label.upper()}]**\n\n{segment.strip()}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(entry)


def main():
    history = load_history()
    lore = load_lore()
    buzz_state = update_buzz(load_buzz())
    buzz_description = describe_buzz(buzz_state)

    raw_response = call_gemini(history, lore, buzz_description)
    segment, segment_label, lore_update = split_response(raw_response)

    if not os.path.exists(LOG_FILE):
        header = (
            f"# {STATION_NAME}\n\n"
            f"The sole broadcasting voice of the kingdom of {KINGDOM_NAME}. "
            f"Awakened {datetime.now(timezone.utc).strftime('%Y-%m-%d')}.\n"
        )
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write(header)

    append_to_log(segment, segment_label)
    if lore_update:
        save_lore(lore_update)
    save_buzz(buzz_state)
    print(
        f"Broadcast segment added: {segment_label} | buzz: {buzz_state['current']}/100"
        + (" (lore updated)" if lore_update else " (no lore update parsed)")
    )


if __name__ == "__main__":
    main()
