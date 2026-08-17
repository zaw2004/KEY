"""bot.py — Patch Credit Bot.

Users upload a sirzipp .so, choose which values to patch (1 credit per patch
operation), give a custom output filename, and receive the patched file.

Requires: pip install "python-telegram-bot"
Fill in BOT_TOKEN (and GITHUB_TOKEN for repo-backed credits) in config.py,
then run:  python3 bot.py
"""
import os
import tempfile
import threading
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          CallbackQueryHandler, filters, ContextTypes)

from config import BOT_TOKEN, ADMIN_ID, PATCH_COST
import credits as cr
from patcher import patch_binary, read_current, PatchError

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
log = logging.getLogger('patchbot')

DATA = {}          # user state: {uid: {'file': path, ...}}
_lock = threading.Lock()


def _state(uid):
    with _lock:
        if uid not in DATA:
            DATA[uid] = {}
        return DATA[uid]


def _clear(uid):
    with _lock:
        DATA.pop(uid, None)


# ---------------- commands ----------------

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    bal = cr.get_credits(uid)
    await update.message.reply_text(
        'Welcome to the *Patch Credit Bot*!\n\n'
        'Upload a sirzipp `.so` file and I will patch it for you.\n'
        'Each patch operation costs *1 credit*.\n\n'
        f'Your credit balance: *{bal}*\n\n'
        'Send me a sirzipp `.so` file to begin.',
        parse_mode='Markdown')


async def cmd_credits(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    bal = cr.get_credits(uid)
    await update.message.reply_text(f'Your credit balance: *{bal}*',
                                    parse_mode='Markdown')


def _admin_only(fn):
    async def wrap(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text('Admins only.')
            return
        return await fn(update, ctx)
    return wrap


@_admin_only
async def cmd_addcredit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        uid, amount = int(ctx.args[0]), int(ctx.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text('Usage: /addcredit <id> <amount>')
        return
    new = cr.add_credits(uid, amount)
    await update.message.reply_text(f'{uid}: {new} credits '
                                    f'({amount:+d}).')


@_admin_only
async def cmd_delcredit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        uid, amount = int(ctx.args[0]), int(ctx.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text('Usage: /delcredit <id> <amount>')
        return
    ok, new = cr.deduct_credits(uid, amount)
    await update.message.reply_text(
        f'{uid}: {new} credits ({"deducted" if ok else "capped at 0"}).')


@_admin_only
async def cmd_checkcredit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(ctx.args[0])
    except (IndexError, ValueError):
        uid = update.effective_user.id
    await update.message.reply_text(
        f'{uid}: {cr.get_credits(uid)} credits.')


# ---------------- file + patch flow ----------------

async def handle_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    f = update.message.document or update.message.audio
    if f is None or not f.file_name.endswith('.so'):
        await update.message.reply_text(
            'Please send a file ending with `.so` (e.g. '
            'sirzipp.cpython-311-x86_64-linux-gnu.so).')
        return

    st = _state(uid)
    st['file'] = os.path.join(tempfile.mkdtemp(prefix='patchbot_'),
                              f.file_name)
    msg = await update.message.reply_text('Downloading file, please wait...')
    await f.download_to_drive(st['file'])

    try:
        cur = read_current(open(st['file'], 'rb').read())
    except PatchError as e:
        _clear(uid)
        await msg.edit_text(f'Sorry, I could not read this file:\n{e}')
        return

    st['cur'] = cur
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton('Admin ID', callback_data='p_admin')],
        [InlineKeyboardButton('Embedded ID', callback_data='p_embed')],
        [InlineKeyboardButton('Bot token', callback_data='p_token')],
        [InlineKeyboardButton('Patch all (1 credit)',
                              callback_data='p_all')],
        [InlineKeyboardButton('Cancel', callback_data='cancel')],
    ])
    txt = ('File received. Current values in your binary:\n'
           f'`admin ID: {cur["admin"]}`\n'
           f'`embedded ID: {cur["embedded"]}`\n'
           f'`token: {cur["token"][:18]}...`\n\n'
           f'Your balance: *{cr.get_credits(uid)}* credits. '
           'Choose what to patch:')
    await msg.edit_text(txt, parse_mode='Markdown', reply_markup=kb)


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    st = _state(uid)
    if not st.get('file') or not os.path.exists(st['file']):
        await q.edit_message_text('Session expired — please send the '
                                  '.so file again (/start).')
        _clear(uid)
        return

    if q.data == 'cancel':
        _clear(uid)
        await q.edit_message_text('Cancelled.')
        return

    if q.data == 'p_all':
        st['want'] = {'admin', 'embed', 'token'}
    else:
        st.setdefault('want', set()).add(q.data.split('_', 1)[1])

    await q.edit_message_text('OK — now send me the new output filename '
                              '(letters, digits, dashes and underscores '
                              'only, e.g. `my_bot.so`):', parse_mode='Markdown')
    st['next'] = 'name'


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Collects the requested input values: output filename, then the new
    values for the selected patches."""
    uid = update.effective_user.id
    st = _state(uid)
    if st.get('next') != 'name':
        return
    name = update.message.text.strip()
    if not name.lower().endswith('.so') or not name.replace('_', '').replace('-', '').isalnum():
        await update.message.reply_text(
            'Invalid name — use letters/digits/dash/underscore and end '
            'with `.so` (e.g. `my_bot.so`):')
        return
    st['out_name'] = name
    st['inputs'] = {}
    st['next'] = 'values'
    await update.message.reply_text(
        f'Output file will be named `{name}`.\n\n'
        f'Your balance: *{cr.get_credits(uid)}* credits. '
        f'Sending it costs *{PATCH_COST} credit*.\n'
        'Type the new values in this format, one per line '
        '(skip with `.`):\n'
        '```'
        'admin: <new admin id>\n'
        'embed: <10-digit new embedded id>\n'
        'token: <new 46-char bot token>'
        '```\n'
        'Only the lines matching the patches you chose will be applied.',
        parse_mode='Markdown')


async def apply_patch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    st = _state(uid)
    if st.get('next') != 'values':
        return
    text = update.message.text
    if '/cancel' in text:
        _clear(uid)
        await update.message.reply_text('Cancelled.')
        return

    want = st['want']
    cur = st['cur']
    vals = {'admin': None, 'embed': None, 'token': None}
    for line in text.splitlines():
        line = line.strip()
        if ':' in line:
            k, v = line.split(':', 1)
            k, v = k.strip().lower(), v.strip()
            if k in vals and v and v != '.':
                vals[k] = v

    need = {'admin' if 'admin' in want else None,
            'embed' if 'embed' in want else None,
            'token' if 'token' in want else None} - {None}
    missing = [k for k in need if not vals[k]]
    if missing:
        await update.message.reply_text(
            'I still need values for: ' +
            ', '.join(f'`{m}`' for m in missing) +
            '. Send them like `key: value` (skip with `.`):')
        return

    cost = PATCH_COST * max(1, len(need))
    bal = cr.get_credits(uid)
    if bal < cost:
        await update.message.reply_text(
            f'Not enough credits. This patch costs {cost} credit(s), '
            f'you have {bal}. Ask the admin to top up.')
        _clear(uid)
        return

    msg = await update.message.reply_text('Patching your binary...')
    try:
        data = open(st['file'], 'rb').read()
        patched, changes = patch_binary(
            data,
            admin=vals['admin'],
            embedded=vals['embed'],
            token=vals['token'])
    except PatchError as e:
        await msg.edit_text(f'Patching failed:\n{e}')
        _clear(uid)
        return

    ok, remaining = cr.deduct_credits(uid, cost)
    if not ok:
        await msg.edit_text('Credit balance changed — '
                            'not enough credits anymore. Please try again.')
        _clear(uid)
        return

    out_path = os.path.join(os.path.dirname(st['file']), st['out_name'])
    open(out_path, 'wb').write(patched)

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton('Patch another file', callback_data='retry')]])
    txt = ('Done! Patched values:\n' +
           '\n'.join('`- ' + c + '`' for c in changes) +
           f'\n\nCredits deducted: {cost}. Balance: {remaining}')
    try:
        await update.message.reply_document(
            document=open(out_path, 'rb'),
            filename=st['out_name'],
            caption=txt, parse_mode='Markdown', reply_markup=kb)
    except TelegramError:
        await msg.edit_text('File was patched but I could not send it — '
                            'please contact the admin.')
        return
    await msg.delete()
    _clear(uid)


async def retry_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _clear(q.from_user.id)
    await cmd_start(update, ctx)


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler('start', cmd_start))
    app.add_handler(CommandHandler('credits', cmd_credits))
    app.add_handler(CommandHandler('addcredit', cmd_addcredit))
    app.add_handler(CommandHandler('delcredit', cmd_delcredit))
    app.add_handler(CommandHandler('checkcredit', cmd_checkcredit))
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.AUDIO, handle_file))
    app.add_handler(CallbackQueryHandler(handle_callback,
                                         pattern=r'^p_(admin|embed|token|all)$|^cancel$'))
    app.add_handler(CallbackQueryHandler(retry_callback, pattern='^retry$'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   handle_text))
    app.run_polling()


if __name__ == '__main__':
    main()
