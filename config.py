# config.py

# It is recommended to use environment variables for sensitive data.
# However, you can hardcode the values here for simplicity.
import os

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "discord token bot token")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "youtube api key")
BOT_OWNER_ID = int(os.environ.get("BOT_OWNER_ID", "Bot Owner ID")) # Replace with your Discord User ID

# You can change the bot's command prefix here
COMMAND_PREFIX = "?"
