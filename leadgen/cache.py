"""Save every API response to disk so a repeated request costs 0 searches."""
import hashlib, json, os


def get_or_fetch(params, fetch_fn, cache_dir="cache"):
    safe = {k: v for k, v in params.items() if k != "api_key"}   # never hash the secret
    key = hashlib.sha1(json.dumps(safe, sort_keys=True).encode()).hexdigest()
    path = os.path.join(cache_dir, key + ".json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    data = fetch_fn(params)
    os.makedirs(cache_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data