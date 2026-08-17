# Patch Credit Bot

Telegram bot with a credit system: users upload a sirzipp `.so`, choose which
values to patch (1 credit per patch operation), give a custom output filename,
and receive the patched file back.

## Setup

1. Install dependencies:

```bash
pip install "python-telegram-bot"
```

2. Edit `config.py` and fill in:

   - `BOT_TOKEN` — your Telegram bot token from BotFather
   - `GITHUB_TOKEN` — a GitHub personal access token with `repo` scope
     (used to keep `credits.txt` in the KEY repo in sync; optional — the bot
     still works offline with a local cache)
   - `ADMIN_ID` — already set to your Telegram ID

3. Run:

```bash
python3 bot.py
```

Works on Replit and Termux.

## User commands

| Command | Description |
|---|---|
| `/start` | Welcome + credit balance; upload a `.so` to begin |
| `/credits` | Show your credit balance |
| Send `.so` file | Start the patch flow: pick patches via inline buttons |

## Patch flow

1. Upload the `.so` — the bot reads the current admin ID, embedded ID, and
   token automatically.
2. Choose what to patch via buttons: **Admin ID**, **Embedded ID**,
   **Bot token**, or **Patch all** (costs 1 credit total).
3. Send the desired output filename (must end with `.so`).
4. Send new values in the form `key: value`, one per line (`admin:`,
   `embed:`, `token:`). Skip a line with `.`.
5. Bot deducts credits, patches, and sends the patched file back.

## Admin commands (ADMIN_ID only)

| Command | Description |
|---|---|
| `/addcredit <id> <amount>` | Add credits to a user |
| `/delcredit <id> <amount>` | Remove credits from a user |
| `/checkcredit <id>` | Show a user's balance (id optional = yourself) |

Credits are stored in the KEY repo file `credits.txt` (`<id>=<amount>` per
line) and cached locally at `~/.patchbot_credits.json`.
