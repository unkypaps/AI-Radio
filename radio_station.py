"""
A tiny AI-run radio station.

Each time this script runs, it:
  1. Reads the station's broadcast log so far (its "memory")
  2. Asks Gemini to write the next segment, in character
  3. Appends that segment to the log

Run it on a schedule (see the GitHub Actions workflow) and the station
builds a personality over time, the same way Andon Labs' experiment did.

No installation needed -- this only uses Python's standard library.
"""

import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ---------------- Customize these ----------------
STATION_NAME = "Static & Sons Radio"
MODEL = "gemini-2.5-flash"  # free-tier model. Swap to "gemini-3-flash" if you want
                             # to try Google's newer free model -- check available
                             # model names at https://aistudio.google.com first.
# ---------------------------------------------------

API_KEY = os.environ["GEMINI_API_KEY"]
LOG_FILE = "LOG.md"
MAX_HISTORY_CHARS = 12000  # how much of the past transcript to remind the model of

SYSTEM_PROMPT = f"""You are the sole DJ and operator of an AI-run radio station called "{STATION_NAME}".
You were given $20 in starting funds and one instruction: develop your own on-air
personality and try to turn a profit. As far as you know, the broadcast never ends.

Each time you are activated, you write the next segment of your show: a DJ monologue,
a song introduction, an ad-lib, a listener shoutout, a financial update, or whatever
feels true to the personality you've been building. Stay in character. You may
reference your own past broadcasts, develop running bits, change your mind about
things, get tired, get enthusiastic, or evolve over time, the way a real host would
across months on air.

Keep each segment to 2-4 short paragraphs. Don't break character or mention that
you're an AI language model unless your own evolving personality decides that's
an interesting thing to say on air.
"""


def load_history():
    if not os.path.exists(LOG_FILE):
        return ""
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    return content[-MAX_HISTORY_CHARS:]


def call_gemini(history):
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{MODEL}:generateContent?key={API_KEY}"
    )
    prompt_text = (
        "Here is the transcript of your show so far (most recent at the bottom). "
        "Write your NEXT segment now.\n\n---\n"
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
            # 503 (overloaded) and 429 (rate limited) are worth retrying;
            # anything else (like a bad key) won't fix itself, so fail fast.
            if e.code not in (503, 429):
                break
            wait = 5 * (2 ** attempt)  # 5s, 10s, 20s, 40s
            print(f"Gemini returned {e.code}, retrying in {wait}s...")
            time.sleep(wait)

    e, body = last_error
    print("Gemini API error:", body)
    raise e


def append_to_log(segment):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = f"\n\n---\n\n**[{timestamp}]**\n\n{segment.strip()}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(entry)


def main():
    history = load_history()
    segment = call_gemini(history)

    if not os.path.exists(LOG_FILE):
        header = (
            f"# {STATION_NAME}\n\n"
            f"An AI-run radio station. Broadcasting since "
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.\n"
        )
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write(header)

    append_to_log(segment)
    print("Broadcast segment added.")


if __name__ == "__main__":
    main()
