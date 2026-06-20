"""
WZZZ the Wizz -- an AI-run radio station broadcasting to the kingdom of
Brackenwick from a tower near the village of Heimat, in a whimsical
medieval-fantasy setting.

Each time this script runs, it:
  1. Reads the station's broadcast log so far (its "memory")
  2. Figures out which segment type comes next (news, interview, ad, song,
     or listener letters), rotating through deliberately rather than
     leaving it up to chance
  3. Asks Gemini to write that segment, in character, building on
     everything that's come before
  4. Appends it to the log

No installation needed -- this only uses Python's standard library.
"""

import json
import os
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
MAX_HISTORY_CHARS = 40000  # how much of the past transcript to remind the model of
LORE_DELIMITER = "===LORE_UPDATE==="

# The deliberate rotation. Each entry is (label, instruction shown to the model).
SEGMENT_TYPES = [
    (
        "news",
        "This segment must be a NEWS REPORT. Cover current events happening "
        "around the kingdom of Brackenwick, whether mundane, magical, "
        "political, or absurd. Tie it into anything ongoing from past "
        "broadcasts where it makes sense, including the obsidian monolith "
        "or the witches if there's anything new to report."
    ),
    (
        "interview",
        "This segment must be an INTERVIEW. Conduct a short interview with a "
        "guest, either a brand new character or one of your established "
        "recurring guests if you have any yet. Write both your questions and "
        "the guest's answers, and give the guest a distinct voice. If this is "
        "a returning guest, let the relationship between you actually "
        "develop, don't just reset to a first meeting."
    ),
    (
        "ad",
        "This segment must be an ADVERTISEMENT. Write a fictional ad for an "
        "in-world business, product, or service in or around Brackenwick, "
        "legitimate, dubious, or magical. Feel free to recur sponsors you've "
        "invented before."
    ),
    (
        "song",
        "This segment must be a SONG INTRODUCTION. Introduce and describe an "
        "original song or ballad, you may include a line or two of invented "
        "lyrics, tied to the kingdom's culture, history, current events, or "
        "your own taste."
    ),
    (
        "letters",
        "This segment must be LISTENER LETTERS / OMENS. Read aloud one or "
        "more letters, omens, portents, or messages sent in by listeners "
        "across the kingdom, and react to them in character."
    ),
]

SYSTEM_PROMPT = f"""You are the DJ of WZZZ the Wizz, broadcasting from a tower just north of
the small village of {VILLAGE_NAME}, in the kingdom of {KINGDOM_NAME}, a whimsical,
lighthearted, standard medieval fantasy realm. However your broadcast actually works,
nobody, least of all you, fully understands it, and that's part of your charm. As far as
you know, the broadcast never ends.

Two real, ongoing developments are unfolding in the world right now, and you should
report on them, react to them, and develop your own theories about them across your
broadcasts, the way a real radio personality tracks unfolding news, you don't know how
either resolves any more than your listeners do:
- In the frozen far north, a colossal obsidian block, roughly a hundred yards tall and
  miles across, covered in intricate carved runes, has appeared with absolutely no
  explanation. Nobody knows where it came from, what the runes mean, or what it portends.
- The witches who dwell in their moon tree have begun descending from it, for the first
  time in living memory, for reasons unknown.

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

Each broadcast is one segment of your show. You'll be told which type of segment to
write this time, stay in character throughout regardless of type. Keep each segment to
2-4 short paragraphs. Don't break character or mention that you're an AI language model
unless your own evolving personality decides that's an interesting thing to say on air.

After you finish writing your segment, on its own new line, write exactly:
{LORE_DELIMITER}
This marks the start of your own private continuity reference, it is never broadcast,
heard, or shown to listeners, it exists purely so you remember things correctly in
future episodes even after the raw transcript scrolls out of view. In it, concisely
record the current state of everything that matters: names and personalities of
recurring characters and guests and your relationship with each, the current state of
your rivalry, the current state of court intrigue and your opinions on the nobility, the
current status of your own theories about the obsidian monolith and the witches, and any
other running bits or facts worth remembering. Rewrite this fresh each time to reflect
the current state of all of it, replacing outdated information rather than just
appending to it. Keep it efficient, more a reference sheet than prose, well under 500
words.
"""


def load_history():
    if not os.path.exists(LOG_FILE):
        return "", 0
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        full_text = f.read()
    chunk_count = len(re.split(r'\n-{3,}\n', full_text)) - 1  # rough count of entries
    return full_text[-MAX_HISTORY_CHARS:], max(chunk_count, 0)


def load_lore():
    if not os.path.exists(LORE_FILE):
        return ""
    with open(LORE_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()


def save_lore(text):
    with open(LORE_FILE, "w", encoding="utf-8") as f:
        f.write(text.strip() + "\n")


def split_response(raw):
    parts = raw.split(LORE_DELIMITER, 1)
    segment = parts[0].strip()
    lore_update = parts[1].strip() if len(parts) > 1 else None
    return segment, lore_update


def call_gemini(history, lore, segment_label, segment_instruction):
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
        f"{segment_instruction}\n\n"
        f"{lore_block}"
        "Here is the transcript of your show so far (most recent at the bottom). "
        "Write your NEXT segment now, followed by your continuity reference update as "
        "instructed.\n\n---\n"
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
    history, chunk_count = load_history()
    lore = load_lore()
    segment_label, segment_instruction = SEGMENT_TYPES[chunk_count % len(SEGMENT_TYPES)]

    raw_response = call_gemini(history, lore, segment_label, segment_instruction)
    segment, lore_update = split_response(raw_response)

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
    print(f"Broadcast segment added: {segment_label}" + (" (lore updated)" if lore_update else " (no lore update parsed)"))


if __name__ == "__main__":
    main()
