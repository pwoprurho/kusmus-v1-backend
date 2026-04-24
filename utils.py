import os
from functools import wraps
from flask import abort, current_app, redirect, url_for, session, request, flash
from flask_login import current_user
from supabase import create_client, Client
from cryptography.fernet import Fernet

def role_required(*roles):
    """
    Decorator to restrict access based on user roles (e.g., 'admin', 'editor').
    Supports both Flask-Login (Admin) and Session-based (Client) auth.
    """
    def wrapper(fn):
        @wraps(fn)
        def decorated_view(*args, **kwargs):
            # 1. Check Flask-Login (Admin/Internal Users)
            if current_user.is_authenticated:
                if current_user.role in roles:
                    return fn(*args, **kwargs)
                # If logged in but role mismatch, continue to check if they are valid 'client' via session?
                # Probably not necessary if they are already logged in as Staff.
                if 'client' in roles and current_user.role != 'client':
                     # If they are admin, they might be allowed depending on logic, 
                     # but typically admin role is distinct.
                     # However, strict checking:
                     pass
            
            # 2. Check Session-based Auth (Clients)
            # Clients use session['client_access'] = True
            if session.get('client_access') is True:
                # We consider them to have role 'client'
                if 'client' in roles:
                    return fn(*args, **kwargs)

            # If neither passed:
            if current_user.is_authenticated:
                 # Logged in as User but wrong role
                 abort(403)
            elif session.get('client_access'):
                 # Logged in as Client but endpoint doesn't allow 'client'
                 abort(403)
            else:
                 # Not logged in at all
                 return redirect(url_for('auth.client_access'))

            return fn(*args, **kwargs) # Fallback (shouldn't reach here due to aborts)
        return decorated_view
    return wrapper

# --- Supabase Client Helper ---

# This helper is needed if a temporary client (using ANON key) is required elsewhere.
def get_anon_client():
    """Returns a new Supabase client using the ANON key for public/auth tasks."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY") 
    if not url or not key:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY in environment.")
    return create_client(url, key)

def get_cipher_suite():
    """Retrieves the encryption key. Fails closed if not configured."""
    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("CRITICAL: ENCRYPTION_KEY not set in environment. Refusing to operate with ephemeral keys.")
    return Fernet(key.encode())

def encrypt_text(text):
    """Encrypts database content."""
    try:
        if not text: return None
        return get_cipher_suite().encrypt(text.encode()).decode()
    except Exception as e:
        print(f"Encryption Error: {e}")
        return None

def decrypt_text(encrypted_text):
    """Decrypts database content."""
    try:
        if not encrypted_text: return ""
        return get_cipher_suite().decrypt(encrypted_text.encode()).decode()
    except Exception:
        return "[CONTENT LOCKED]"