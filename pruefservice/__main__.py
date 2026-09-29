import os

import uvicorn
from dotenv import load_dotenv

from pruefservice.app import build_app, configure_telemetry

load_dotenv()
configure_telemetry()
uvicorn.run(build_app(), host="0.0.0.0", port=int(os.getenv("PORT", "8000")), log_level="info")
