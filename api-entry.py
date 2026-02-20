import sys
import os
import logging

# Ensure root is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Basic logging early on
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api-entry")

try:
    logger.info("Initializing api-entry...")
    from api.main import app
    logger.info("FastAPI app imported successfully.")
except Exception as e:
    logger.error(f"Failed to import app from api.main: {e}")
    import traceback
    logger.error(traceback.format_exc())
    # Re-raise so Vercel can see the failure in logs
    raise

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
