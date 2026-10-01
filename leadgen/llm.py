"""Thin, swappable LLM client (Gemini free tier).
Cached on disk, rate-limited, and fails safe: any problem returns None so callers fall back to rules."""
import hashlib
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")   # use any Flash model AI Studio lists as free
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MIN_GAP = 4.5      # seconds between live calls, about 13 per minute
RETRY_ON = ("HTTP 429", "HTTP 500", "HTTP 503")   # rate limit or busy server: wait and try again
_last_call = 0.0


def available():
    return bool(os.getenv("GEMINI_API_KEY"))


def _call(prompt):
    global _last_call
    wait = MIN_GAP - (time.time() - _last_call)
    if wait > 0:
        time.sleep(wait)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    r = requests.post(
        URL.format(model=MODEL),
        json=body,
        timeout=60,
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
    )
    _last_call = time.time()
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def ask_json(prompt, cache_dir="data/llm_cache"):
    """Return a parsed JSON object, or None on any failure (the reason is printed)."""
    key = hashlib.sha1((MODEL + prompt).encode("utf-8")).hexdigest()
    path = os.path.join(cache_dir, key + ".json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    if not available():
        print("LLM: GEMINI_API_KEY not found in .env", file=sys.stderr)
        return None
    for attempt in range(4):
        try:
            data = json.loads(_call(prompt))
            os.makedirs(cache_dir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            return data
        except Exception as e:
            print(f"LLM error (attempt {attempt + 1}): {str(e)[:120]}", file=sys.stderr)
            if any(code in str(e) for code in RETRY_ON):
                time.sleep(15 * (attempt + 1))
                continue
            return None
    return None


if __name__ == "__main__":
    print("key found:", available(), "| model:", MODEL)
    print(ask_json('Return only this JSON: {"ok": true, "word": "hello"}'))