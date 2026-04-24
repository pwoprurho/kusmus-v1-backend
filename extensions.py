import os
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Restrict origins in prod; allow all in dev if not specified
socketio = SocketIO(cors_allowed_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","))

# Rate Limiting
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)
