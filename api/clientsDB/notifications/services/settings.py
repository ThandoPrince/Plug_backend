import os
from dotenv import load_dotenv

load_dotenv()  # Load .env file if not already loaded

HMS_APP_ID = os.getenv("HMS_APP_ID", "")
HMS_APP_SECRET = os.getenv("HMS_APP_SECRET", "")