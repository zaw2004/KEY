# ============================================================
# config.py — Patch Credit Bot configuration
# Fill in YOUR Telegram bot token below (from BotFather).
# ============================================================

BOT_TOKEN = 'PASTE_YOUR_BOT_TOKEN_HERE'

# Admin who can run /addcredit /delcredit /checkcredit
ADMIN_ID = 1767590675

# GitHub repo used for credit storage
GITHUB_OWNER = 'zaw2004'
GITHUB_REPO = 'KEY'
# Personal access token with repo write access
GITHUB_TOKEN = 'PASTE_YOUR_GITHUB_TOKEN_HERE'

# Credit file inside the repo
CREDITS_FILE = 'credits.txt'   # format: <telegram_id>=<credits>  (one per line)

# Price per patch operation
PATCH_COST = 1
