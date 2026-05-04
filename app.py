import eventlet
eventlet.monkey_patch()

import os
import traceback
from dotenv import load_dotenv
from flask import Flask, render_template, redirect, url_for, request, session
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_talisman import Talisman
from werkzeug.middleware.proxy_fix import ProxyFix
from cachetools import TTLCache
from models import User

# =========================================================
# 1. ENVIRONMENT & APP FACTORY
# =========================================================
load_dotenv()

app = Flask(__name__)
ENVIRONMENT = os.getenv('FLASK_ENV', 'development')
IS_SECURE = ENVIRONMENT == 'production'

app.secret_key = os.getenv("SECRET_KEY")
if not app.secret_key:
    if IS_SECURE:
        raise RuntimeError("CRITICAL: SECRET_KEY environment variable is missing in production.")
    app.secret_key = "dev_secret_key_change_in_production"

# Domain & SEO
if os.getenv("PREFERRED_URL_SCHEME"):
    app.config["PREFERRED_URL_SCHEME"] = os.getenv("PREFERRED_URL_SCHEME")

# =========================================================
# 2. SESSION SECURITY (Single Source of Truth)
# =========================================================
# Flask's session cookie config is the ONLY authority.
# Talisman will NOT override these — we pass them through explicitly.
app.config.update(
    SESSION_COOKIE_SECURE=IS_SECURE,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=7200,  # 2 hours
)

# =========================================================
# 3. CSRF PROTECTION
# =========================================================
app.config.update(
    WTF_CSRF_SSL_STRICT=IS_SECURE,  # Enforce strict HTTPS checking in production (ProxyFix handles Proto fallback)
    WTF_CSRF_TIME_LIMIT=7200,       # Match session lifetime
)
csrf = CSRFProtect(app)

# =========================================================
# 4. TRANSPORT SECURITY (Talisman + ProxyFix)
# =========================================================
# ProxyFix MUST wrap BEFORE Talisman so Talisman sees the real scheme.
# Both run in ALL environments — ProxyFix is a no-op without proxy headers.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Talisman: always active for security headers (X-Frame-Options, X-XSS, etc.)
# force_https and session_cookie_secure are driven by IS_SECURE.
# We explicitly disable Talisman's session cookie override to avoid
# conflicting with Flask's authoritative SESSION_COOKIE_SECURE config.
Talisman(app,
    content_security_policy={
        'default-src': "'self'",
        'script-src': [
            "'self'",
            "'unsafe-inline'",  # Needed until major script refactor
            "https://cdnjs.cloudflare.com",
            "https://cdn.jsdelivr.net",
        ],
        'style-src': [
            "'self'",
            "'unsafe-inline'",  # Essential for current legacy styling
            "https://fonts.googleapis.com",
            "https://cdnjs.cloudflare.com",
        ],
        'font-src': [
            "'self'",
            "https://fonts.gstatic.com",
            "https://cdnjs.cloudflare.com",
        ],
        'img-src': ["'self'", "data:"],
        'connect-src': ["'self'", "ws:", "wss:"],
    },
    force_https=IS_SECURE,
    session_cookie_secure=IS_SECURE,
    session_cookie_http_only=True,
    session_cookie_samesite='Lax',
)

from core.logger import setup_logger
app.logger = setup_logger(app)

# =========================================================
# 5. EXTENSIONS & DATABASE
# =========================================================
from extensions import socketio, limiter
socketio.init_app(app)
limiter.init_app(app)

from db import supabase_admin, safe_execute

# =========================================================
# 6. BLUEPRINTS
# =========================================================
from routes.sandbox import sandbox_bp
from routes.public import public_bp
from routes.auth import auth_bp
from routes.admin import admin_bp
from routes.tax import tax_bp
from routes.physics_sandbox import physics_bp
from routes.sovereign import sovereign_bp, init_csrf_exemptions
from routes.hive import hive_bp

# Sovereign API and Hive sync use Bearer tokens/Node IDs, not browser sessions — exempt from CSRF.
init_csrf_exemptions(csrf)
csrf.exempt(hive_bp)

app.register_blueprint(public_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(sandbox_bp)
app.register_blueprint(tax_bp)
app.register_blueprint(physics_bp)
app.register_blueprint(sovereign_bp)
app.register_blueprint(hive_bp)

# --- CACHING LAYER ---
# Cache user profiles for 10 minutes (600 seconds) to avoid redundant DB hits
user_cache = TTLCache(maxsize=100, ttl=600)

# =========================================================
# 7. AUTHENTICATION (Flask-Login)
# =========================================================
login_manager = LoginManager()
login_manager.login_view = 'auth.client_access'
login_manager.login_message = "Authentication required to proceed."
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    """
    Cached session loader. We trust Flask's signed session cookie
    and only query the DB if the profile is not in the local TTL cache.
    """
    if not supabase_admin or not user_id:
        return None
    
    # Check cache first
    cached_user = user_cache.get(user_id)
    if cached_user:
        return cached_user

    try:
        response = safe_execute(
            supabase_admin.table('user_profiles')
            .select('*')
            .eq('id', user_id)
            .single()
        )
        if response.data:
            data = response.data
            user = User(
                id=data['id'],
                full_name=data.get('full_name'),
                email=data.get('email'),
                role=data.get('role'),
                location=data.get('location')
            )
            # Store in cache
            user_cache[user_id] = user
            return user
        return None
    except Exception as e:
        print(f"Session Load Error: {e}")
        traceback.print_exc()
        return None

# =========================================================
# 8. SOCKET EVENTS (Decoupled from auth & AI agents)
# =========================================================
import socket_events

# =========================================================
# 9. ERROR HANDLERS
# =========================================================
@app.errorhandler(403)
def access_forbidden(e):
    return render_template('403.html'), 403

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

# =========================================================
# 10. RESPONSE SECURITY HEADERS
# =========================================================
@app.after_request
def add_security_headers(response):
    """
    Enforce noindex on all sensitive routes so search engines
    never crawl admin, auth, or internal kus_bot endpoints.
    """
    sensitive_prefixes = ('/admin', '/auth', '/sandbox', '/tax', '/physics', '/client')
    if getattr(request, 'path', '').startswith(sensitive_prefixes):
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response

# =========================================================
# 11. ENTRYPOINT
# =========================================================
if __name__ == "__main__":
    socketio.run(app, debug=True, host="0.0.0.0", port=8000)