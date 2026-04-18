import os

PREFIX = os.getenv("DISCORD_BOT_PREFIX", "=")
DEV_ID = int(os.getenv("DEV_ID", "175386962364989440"))
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
MONGO_URL = os.getenv("DISCORD_MONGO_URL")
MONGO_DB = os.getenv("MONGO_DB", "testgatesdb")
ENVIRONMENT = os.getenv("ENVIRONMENT", "testing")
