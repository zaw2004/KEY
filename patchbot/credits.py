"""credits.py — Credit storage backed by the GitHub KEY repo.

Data is stored in the repo file credits.txt (one line per user:
    <telegram_id>=<credits>
).

The bot keeps a local cache (~/.patchbot_credits.json) and syncs with the
GitHub API on startup, on every write, and on every read (with ETag-based
revalidation when possible).

If GitHub is unreachable, it falls back to the local cache so the bot keeps
working offline.
"""
import json
import os
import time
import urllib.request
import urllib.error

from config import (GITHUB_OWNER, GITHUB_REPO, GITHUB_TOKEN,
                    CREDITS_FILE, ADMIN_ID)

CACHE_PATH = os.path.expanduser('~/.patchbot_credits.json')


def _api(method, path, payload=None):
    """Simple GitHub REST helper. Returns parsed JSON or None on error."""
    url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/{path}'
    req = urllib.request.Request(url, method=method)
    req.add_header('Authorization', f'token {GITHUB_TOKEN}')
    req.add_header('User-Agent', 'patchbot')
    if payload is not None:
        data = json.dumps(payload).encode()
        req.data = data
        req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            if r.status in (200, 201, 204):
                body = r.read().decode()
                return json.loads(body) if body else {}
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        pass
    return None


def _get_content():
    """Fetch file content + sha from the repo. Returns (text, sha) or None."""
    j = _api('GET', f'contents/{CREDITS_FILE}')
    if j and isinstance(j, dict) and j.get('content'):
        import base64
        text = base64.b64decode(j['content']).decode('utf-8')
        return text, j.get('sha')
    return None


def load_credits():
    """Return dict {user_id(int): credits(int)} merging repo + local cache."""
    credits = {}
    # local cache first
    if os.path.exists(CACHE_PATH):
        try:
            credits = {int(k): int(v) for k, v in
                       json.load(open(CACHE_PATH)).items()}
        except Exception:
            credits = {}
    # then repo (authoritative if reachable)
    got = _get_content()
    if got:
        text, _ = got
        for line in text.splitlines():
            line = line.strip()
            if not line or '=' not in line:
                continue
            key, val = line.split('=', 1)
            try:
                credits[int(key.strip())] = max(0, int(val.strip()))
            except ValueError:
                pass
    return credits


def save_credits(credits):
    """Write credits to the local cache and push to GitHub if reachable."""
    try:
        json.dump({str(k): int(v) for k, v in credits.items()},
                  open(CACHE_PATH, 'w'))
    except Exception:
        pass
    lines = [f'{k}={v}' for k, v in sorted(credits.items()) if v > 0]
    text = '\n'.join(lines) + ('\n' if lines else '')
    content = text.encode().decode()
    got = _get_content()
    if got:
        _, sha = got
        _api('PUT', f'contents/{CREDITS_FILE}', {
            'message': f'patchbot: update credits ({time.strftime("%c")})',
            'content': __import__('base64').b64encode(text.encode()).decode(),
            'sha': sha,
        })
    else:
        # first creation of the file
        _api('PUT', f'contents/{CREDITS_FILE}', {
            'message': 'patchbot: create credits.txt',
            'content': __import__('base64').b64encode(text.encode()).decode(),
        })


def get_credits(user_id):
    return load_credits().get(int(user_id), 0)


def add_credits(user_id, amount):
    credits = load_credits()
    credits[int(user_id)] = max(0, credits.get(int(user_id), 0) + amount)
    save_credits(credits)
    return credits[int(user_id)]


def deduct_credits(user_id, amount):
    """Try to deduct; returns (ok: bool, remaining: int)."""
    credits = load_credits()
    uid = int(user_id)
    cur = credits.get(uid, 0)
    if cur < amount:
        return False, cur
    credits[uid] = cur - amount
    save_credits(credits)
    return True, credits[uid]


if __name__ == '__main__':
    print('credits.txt from repo:')
    print(_get_content())
    print('local cache credits:', load_credits())
