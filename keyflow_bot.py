#!/usr/bin/env python3
"""
Key Request Workflow — RUIJIE ASYNC EXTREME
=============================================
Overlay script that adds an automatic license-key request system to the
sirzipp bot, WITHOUT touching the compiled .so binary.

How it works
------------
1. Buyer  : sends /requestkey  -> bot asks for their machine's system key
2. Buyer  : replies with system key (the number from running
            get_system_key() on their server)
3. Admin  : gets a notification with [✅ Approve] / [❌ Reject] buttons
4. Admin  : clicks Approve -> the key is written to the GitHub KEY repo
            (allinone.txt) and the buyer is notified

Why the system key?
-------------------
The compiled binary checks the license by comparing the GitHub key file
("system_key,expiry" lines) against get_system_key() of the running
machine. A Telegram ID alone can never pass that check, so the buyer must
supply their machine's fingerprint once.
"""
import asyncio
import base64
import datetime
import json
import os
import sys
import traceback

# ---------- 1. Prepare before importing sirzipp -----------------------------
# sirzipp's module init AUTO-STARTS its own Telegram bot (run_polling).
# Mock it so the binary's bot never starts; we run our own Application on the
# same token instead (the binary's handler registrations stay dormant).
import telegram.ext as _ext

_ORIG_RUN_POLLING = _ext.Application.run_polling
_ext.Application.run_polling = lambda self, *a, **kw: None  # no-op

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sirzipp

# Restore the real run_polling for our own Application
_ext.Application.run_polling = _ORIG_RUN_POLLING
_ext.Application.run_polling_stop = getattr(
    _ext.Application, 'run_polling_stop', None)
_ext.Application.run_updater = getattr(
    _ext.Application, 'run_updater', None)

# ---------- 2. Constants (taken straight from the binary) -------------------
BOT_TOKEN = sirzipp.BOT_TOKEN
# The PAT embedded in the binary is fine-grained and can only READ the repo
# (PUT returns 403 "Resource not accessible by personal access token").
# Writing needs a classic token with contents:rw scope. Priority:
#   1. GITHUB_WRITE_TOKEN env var
#   2. sirzipp.GITHUB_TOKEN (embedded PAT)
#   3. `gh auth token` (only works on machines with gh CLI logged in)
GITHUB_TOKEN = (os.environ.get('GITHUB_WRITE_TOKEN') or
                sirzipp.GITHUB_TOKEN)
GITHUB_OWNER = sirzipp.GITHUB_OWNER
GITHUB_REPO = sirzipp.GITHUB_REPO
DEFAULT_EXPIRY_DAYS = 365          # default license length
PENDING_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'pending_requests.json')
HOURS = 48                         # request auto-expiry


def encrypt_key_data(key: str, expiry: str) -> str:
    import hashlib
    return hashlib.sha256(f'{key}|{expiry}'.encode()).hexdigest()


# ---------- 3. Pending-request store ----------------------------------------
def load_pending() -> dict:
    try:
        with open(PENDING_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_pending(data: dict) -> None:
    tmp = PENDING_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, PENDING_FILE)


def purge_expired(data: dict) -> dict:
    now = datetime.datetime.utcnow()
    out = {k: v for k, v in data.items()
           if (datetime.datetime.fromisoformat(v['ts'])
               + datetime.timedelta(hours=HOURS)) > now}
    return out


def _expiry_str(days: int = DEFAULT_EXPIRY_DAYS) -> str:
    return (datetime.datetime.utcnow() + datetime.timedelta(days=days)
            ).strftime('%Y-%m-%d %H:%M:%S')


# ---------- 4. GitHub repo writer -------------------------------------------
def _github_headers():
    return {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'keyflow-bot',
    }


def repo_get(path: str):
    import requests
    url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}'
    r = requests.get(url, headers=_github_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def repo_commit_file(path: str, content: str, message: str) -> dict:
    import requests
    url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}'
    try:
        meta = repo_get(path)
        sha = meta['sha']
        old = base64.b64decode(meta['content']).decode('utf-8')
    except Exception:
        sha = None
        old = ''
    lines = [l for l in old.splitlines() if l.strip()]
    # dedupe: remove existing line(s) with the same key (first field)
    new_key = content.split(',')[0].strip()
    seen = set()
    new_lines = []
    for l in lines:
        key = l.split(',')[0].strip()
        if key == new_key:
            continue          # drop old entry for the same machine
        if key not in seen:
            seen.add(key)
            new_lines.append(l)
    new_lines.append(content)
    payload = {
        'message': message,
        'content': base64.b64encode('\n'.join(new_lines).encode()
                                    ).decode(),
    }
    if sha:
        payload['sha'] = sha
    r = requests.put(url, headers=_github_headers(), json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


# ---------- 5. Telegram handlers --------------------------------------------
AWAITING_KEY = {}   # telegram_id -> request_id


async def cmd_requestkey(update, context):
    user = update.effective_user
    rid = f'{user.id}_{int(asyncio.get_event_loop().time())}'
    data = load_pending()
    data[rid] = {
        'telegram_id': user.id,
        'username': user.username or '',
        'ts': datetime.datetime.utcnow().isoformat(),
        'status': 'awaiting_key',
    }
    save_pending(data)
    AWAITING_KEY[user.id] = rid
    await update.message.reply_text(
        '🔑 Key တောင်းရန် သင့် server (Replit) Shell ထဲမှာ ဒီ command ကို run ပြီး '
        'ထွက်လာတဲ့ ဂဏန်းကို ဒီ chat ထဲ ပြန်ပို့ပေးပါ:\n\n'
        'python3 -c "import sys; sys.path.insert(0,\'.\'); import sirzipp; '
        'print(sirzipp.get_system_key())"\n\n'
        '၄၈ နာရီအတွင်း ပြန်မပို့ရင် request ပျက်သွားမှာပါ။')


async def handle_key_submission(update, context):
    """Any plain text while the user is awaiting key entry."""
    text = (update.message.text or '').strip()
    if not text or text.startswith('/'):
        return
    uid = update.effective_user.id
    rid = AWAITING_KEY.get(uid)
    if not rid:
        return
    data = load_pending()
    if rid not in data:
        await update.message.reply_text('❌ Request မရှိတော့ပါ။ /requestkey နဲ့ ပြန်စပါ။')
        del AWAITING_KEY[uid]
        return
    key = text.split()[0]  # take first whitespace-free token
    data[rid]['system_key'] = key
    data[rid]['status'] = 'pending_admin'
    save_pending(data)
    await update.message.reply_text(
        f'✅ Key {key} ဖမ်းယူပြီးပါပီ။ Admin အတည့်ပြုချက် စောင့်နေပါ...')
    del AWAITING_KEY[uid]
    # notify admin
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(f'🔔 Key request အသစ်:\n'
                      f'User: {data[rid]["username"]} (ID {uid})\n'
                      f'System key: {key}\n'
                      f'⏳ ၄၈ နာရီအတွင်း အတည့်ပြုပေးပါ။'),
                reply_markup=_admin_markup(rid, uid))
        except Exception as e:
            print('admin notify error:', e)


def _admin_markup(rid, uid):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([[
        InlineKeyboardButton('✅ Approve', callback_data=f'btn_approve_{rid}'),
        InlineKeyboardButton('❌ Reject', callback_data=f'btn_reject_{rid}'),
    ]])


async def cmd_pending(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return
    data = load_pending()
    pending = {k: v for k, v in data.items() if v['status'] == 'pending_admin'}
    if not pending:
        await update.message.reply_text('📭 Pending request မရှိပါ။')
        return
    for rid, v in pending.items():
        await update.message.reply_text(
            f'🔔 {v["username"]} (ID {v["telegram_id"]}) — '
            f'key: {v["system_key"]}\n'
            f'တောင်းသည့်အချိန်: {v["ts"]}',
            reply_markup=_admin_markup(rid, v['telegram_id']))


async def handle_callbacks(update, context):
    data = update.callback_query.data or ''
    if data.startswith('btn_approve_'):
        rid = data[len('btn_approve_'):]
        store = load_pending()
        req = store.get(rid)
        if not req:
            await update.callback_query.answer('Request မရှိတော့ပါ။', show_alert=True)
            return
        try:
            expiry = _expiry_str(DEFAULT_EXPIRY_DAYS)
            raw_line = f'{req["system_key"]},{expiry}'
            repo_commit_file(
                'allinone.txt', raw_line,
                f'Auto key for Telegram ID {req["telegram_id"]} '
                f'({req["username"]})')
            store[rid]['status'] = 'approved'
            save_pending(store)
            await update.callback_query.edit_message_text(
                f'✅ Approved! Key {req["system_key"]} → allinone.txt '
                f'(expires {expiry})')
            await context.bot.send_message(
                chat_id=req['telegram_id'],
                text=f'🎉 Key အတည့်ပြုပြီးပါပီ!\n'
                     f'System key: {req["system_key"]}\n'
                     f'သက်တမ်း: {expiry}\n'
                     f'Bot ကို ပြန် run ပါ — Access Granted ရပါမယ်။')
        except Exception as e:
            traceback.print_exc()
            await update.callback_query.answer(
                f'❌ Error: {e}', show_alert=True)
    elif data.startswith('btn_reject_'):
        rid = data[len('btn_reject_'):]
        store = load_pending()
        req = store.get(rid)
        if req:
            store[rid]['status'] = 'rejected'
            save_pending(store)
            await update.callback_query.edit_message_text(
                '❌ Rejected.')
            try:
                await context.bot.send_message(
                    chat_id=req['telegram_id'],
                    text='❌ Key request ပယ်ဖျက်ခံရပါတယ်။')
            except Exception:
                pass
        else:
            await update.callback_query.answer('Request မရှိတော့ပါ။',
                                               show_alert=True)
    await update.callback_query.answer()


# ---------- 6. App bootstrap -------------------------------------------------
ADMIN_IDS = list(getattr(sirzipp, 'ADMIN_IDS', []))


def main():
    from telegram import BotCommand
    from telegram.ext import (Application, CallbackQueryHandler,
                              CommandHandler, MessageHandler, filters)

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler('requestkey', cmd_requestkey))
    app.add_handler(CommandHandler('pending', cmd_pending))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_key_submission))

    print('[KEYFLOW] Bot started (admin IDs:', ADMIN_IDS, ')')
    # run_polling() in PTB 22 is a blocking method (returns None) that manages
    # the event loop itself — do NOT wrap it in asyncio.run().
    while True:
        try:
            app.run_polling(allowed_updates=['message', 'callback_query'],
                            drop_pending_updates=False)
            break
        except Exception as exc:  # noqa: BLE001
            import time
            print('[KEYFLOW] Polling error / conflict:', exc)
            print('[KEYFLOW] Retrying in 10s ...')
            time.sleep(10)


if __name__ == '__main__':
    main()
