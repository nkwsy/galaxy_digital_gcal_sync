"""Launch the web viewer locally.

Reads:
  WEB_PASSWORD   required, else web.py returns 503 on every request.
  WEB_USERNAME   default 'volunteer'
  WEB_HOST       default '127.0.0.1' (bind to localhost only)
  WEB_PORT       default 8765
  GALAXY_DB_PATH default 'galaxy_sync.sqlite3'

Run: python run_web.py
"""
import os
import uvicorn
from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    if not os.getenv("WEB_PASSWORD"):
        print("WARNING: WEB_PASSWORD is not set; the server will refuse all "
              "requests with HTTP 503. Set WEB_PASSWORD in .env before "
              "exposing the page.")
    uvicorn.run(
        "web:app",
        host=os.getenv("WEB_HOST", "127.0.0.1"),
        port=int(os.getenv("WEB_PORT", "8765")),
        log_level=os.getenv("WEB_LOG_LEVEL", "info"),
    )
