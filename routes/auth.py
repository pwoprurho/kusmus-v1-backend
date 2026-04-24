
import os
import secrets
import random
import traceback
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import login_user, logout_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from supabase import create_client
from db import supabase_admin, safe_execute
from models import User, ClientUser 
from services.mailer import send_recovery_otp
from extensions import limiter


def rotate_session():
    """
    Production-grade session rotation for login.
    Prevents session fixation attacks by clearing user data,
    while preserving framework state (CSRF token, flash queue)
    that must survive across the redirect.
    """
    # Preserve CSRF token and pending flash messages
    csrf_token = session.get('csrf_token')
    flashes = session.get('_flashes', [])
    
    session.clear()
    
    # Restore framework state
    if csrf_token:
        session['csrf_token'] = csrf_token
    if flashes:
        session['_flashes'] = flashes

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

# === RECOVERY OTP ENDPOINT ===
@auth_bp.route('/send-recovery', methods=['POST'])
@limiter.limit("5 per minute")
def send_recovery():
    email = request.json.get('email')
    if not email: return jsonify({'error': 'Email required'}), 400
    
    try:
        # Check if client exists
        client_res = safe_execute(supabase_admin.table('clients').select('id').eq('email', email))
        if client_res.data and len(client_res.data) > 0:
            # Generate 6-digit OTP
            otp = ''.join([str(secrets.randbelow(10)) for _ in range(6)])
            session['recovery_otp'] = otp
            session['recovery_email'] = email
            
            # Send Email
            from services.mailer import send_recovery_otp
            send_recovery_otp(email, otp)
            
            return jsonify({'success': True, 'message': 'If this email is registered, a recovery code has been sent.'})
        else:
            # Generic success message delays brute force and thwarts enumeration
            import time
            time.sleep(0.5) # Simulate email delay
            return jsonify({'success': True, 'message': 'If this email is registered, a recovery code has been sent.'})
    except Exception as e:
        # Don't leak DB errors to client
        return jsonify({'error': 'An internal error occurred.'}), 500


# === CLIENT TOKEN HANDSHAKE ROUTE ===
@auth_bp.route('/client-token', methods=['POST'])
def client_token():
    # Only allow if client session is valid
    if not session.get('client_access') or not session.get('client_id'):
        return jsonify({'error': 'Not authenticated'}), 401
    # Generate a secure token and store in session
    token = secrets.token_urlsafe(32)
    session['client_token'] = token
    return jsonify({'client_token': token, 'client_id': session.get('client_id')})

# Helper: Create a temp client (Safe)
def get_auth_client():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY") 
    if not url or not key:
        print(f"DEBUG AUTH: get_auth_client failed - URL: {bool(url)}, KEY: {bool(key)}")
        return None
    return create_client(url, key)

# --- LEGACY ADMIN LOGIN REDIRECT ---
# Redirects old admin login URL to the unified access page
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    return redirect(url_for('auth.client_access'))

# =========================================================
# === UNIFIED SECURE ACCESS (Zero Trust) ===
# =========================================================

@auth_bp.route('/client-access', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def client_access():
    if request.method == 'POST':
        email_raw = (request.form.get('email') or '').strip()
        email_lower = email_raw.lower()
        auth_input = (request.form.get('auth_input') or '').strip()

        # --- ZERO TRUST: Input Validation ---
        if not email_raw or '@' not in email_raw or not auth_input:
            flash("All fields are required.", "error")
            return render_template('client/client_access.html')

        # === PHASE 1: CLIENT AUTH (Primary) ===
        try:
            # Case-Insensitive Lookup for Clients
            client_res = safe_execute(supabase_admin.table('clients').select('*').ilike('email', email_lower))
            print(f"DEBUG AUTH: Phase 1 (Client Table) Check for {email_lower} - Found: {len(client_res.data) > 0 if client_res.data else 0}")

            if client_res.data and len(client_res.data) > 0:
                client_data = client_res.data[0]
                email = client_data['email'] # Use the canonical email from DB

                # Check for Valid Session OTP (OR Master Key)
                session_otp = session.get('recovery_otp')
                is_valid_otp = (
                    session_otp
                    and auth_input == session_otp
                    and session.get('recovery_email') == email
                )

                # Case 1: RECOVERY (OTP or Recovery Key)
                if is_valid_otp or auth_input == client_data.get('recovery_key'):
                    session['temp_client_email'] = email
                    session['temp_client_key'] = auth_input
                    if is_valid_otp:
                        session.pop('recovery_otp', None)  # Consume OTP
                        flash("Identity Verified. Proceed to Credential Reset.", "info")
                    else:
                        flash("Master Key Accepted. Proceed to Credential Reset.", "info")
                    return redirect(url_for('auth.client_setup'))

                # Case 2: PASSWORD LOGIN
                if client_data.get('password_hash') and check_password_hash(client_data['password_hash'], auth_input):
                    # Zero Trust: Rotate session to prevent fixation, preserve CSRF
                    rotate_session()
                    session['client_access'] = True
                    session['client_id'] = client_data['id']
                    session['client_email'] = email
                    flash("Secure Channel Established.", "success")
                    return redirect(url_for('public.client_dashboard'))

            # Case 3: FIRST TIME REGISTRATION (Verification Code)
            # Registration is also case-insensitive for the email match
            audit_res = safe_execute(supabase_admin.table('audit_requests')\
                .select('*').ilike('email', email_lower).eq('verification_code', auth_input))

            if audit_res.data and len(audit_res.data) > 0:
                email = audit_res.data[0]['email'] # Canonical email
                session['temp_client_email'] = email
                session['temp_client_key'] = auth_input
                session['temp_client_name'] = audit_res.data[0]['name']
                session['temp_client_phone'] = audit_res.data[0].get('phone')
                flash("Identity Verified. Initialize Security Protocol.", "success")
                return redirect(url_for('auth.client_setup'))

        except Exception as e:
            msg = str(e)
            print(f"DEBUG AUTH: Phase 1 (Client Auth) failure: {msg}")
            if "illegal request line" in msg.lower():
                flash("A temporary connection issue occurred. Please retry.", "error")
            else:
                flash("An internal error occurred. Please try again later.", "error")
            return render_template('client/client_access.html')

        try:
            temp_client = get_auth_client()
            if temp_client:
                # Try raw email first, then retry with lowercase if it differs
                auth_attempts = [email_raw]
                if email_lower != email_raw: auth_attempts.append(email_lower)
                
                auth_res = None
                last_error = None
                
                for email_to_try in auth_attempts:
                    try:
                        # Removed safe_retry for sensitive auth check; HTTP/1.1 fix handles proxy stability.
                        auth_res = temp_client.auth.sign_in_with_password(
                            {"email": email_to_try, "password": auth_input}
                        )
                        if auth_res.user: break
                    except Exception as attempt_err:
                        last_error = attempt_err
                        continue
                
                if auth_res and auth_res.user:
                    print(f"DEBUG AUTH: Phase 2 (Admin Auth) Success for {email_to_try}")
                    response = safe_execute(supabase_admin.table('user_profiles').select('*').eq('id', auth_res.user.id).single())
                    if response.data:
                        data = response.data
                        user = User(
                            data['id'], data.get('full_name'),
                            data.get('email'), data.get('role', 'intern'),
                            data.get('location')
                        )
                        # Security Hardening: Rotate session, preserve CSRF, store JWT
                        rotate_session()
                        session['supabase_token'] = auth_res.session.access_token
                        login_user(user)
                        flash("Secure Channel Established.", "success")
                        return redirect(url_for('admin.dashboard'))
                elif last_error:
                    raise last_error
        except Exception as e:
            error_msg = str(e)
            print(f"DEBUG AUTH: Phase 2 (Admin Auth) failure: {error_msg}")
            traceback.print_exc()
            
            # Extract readable message if possible
            if "illegal request line" in error_msg.lower():
                flash("Proxy Error: Illegal Request Line. Please retry.", "error")
            elif "invalid login credentials" in error_msg.lower():
                 flash("Access Denied: Invalid login credentials.", "error")
            else:
                flash(f"System Error: {error_msg}", "error")
            return render_template('client/client_access.html')

        # === FINAL FALLBACK ===
        # If we reached here, both Client DB and Admin Auth failed without raising exceptions.
        flash("Access Denied: Credentials NOT recognized in any system.", "error")

    return render_template('client/client_access.html')

@auth_bp.route('/client-setup', methods=['GET', 'POST'])
def client_setup():
    # Security Gate
    if not session.get('temp_client_email') or not session.get('temp_client_key'):
        return redirect(url_for('auth.client_access'))

    if request.method == 'POST':
        password = request.form.get('password')
        confirm = request.form.get('confirm_password')
        phone = request.form.get('phone')
        
        if password != confirm:
            flash("Passwords do not match.", "error")
            return redirect(url_for('auth.client_setup'))

        # Password policy enforcement
        if len(password) < 12:
            flash("Password must be at least 12 characters.", "error")
            return redirect(url_for('auth.client_setup'))
        if not any(c.isdigit() for c in password) or not any(c.isupper() for c in password):
            flash("Password must contain at least one uppercase letter and one digit.", "error")
            return redirect(url_for('auth.client_setup'))

        hashed_pw = generate_password_hash(password)
        email = session.get('temp_client_email')
        key = session.get('temp_client_key')
        name = session.get('temp_client_name', 'Valued Client')
        # Use phone from form if provided, else session fallback
        client_phone = phone or session.get('temp_client_phone')
        
        
        try:
            existing = safe_execute(supabase_admin.table('clients').select('id').eq('email', email))
            client_id = None
            
            if existing.data:
                # UPDATE (Password Reset)
                safe_execute(supabase_admin.table('clients').update({
                    'password_hash': hashed_pw,
                    'phone': client_phone
                }).eq('email', email))
                
                client_id = existing.data[0]['id']
                flash("Credentials Updated. Logging in...", "success")
            else:
                # INSERT (New Registration)
                # We execute and return data to get the new UUID immediately
                insert_res = safe_execute(supabase_admin.table('clients').insert({
                    'email': email,
                    'password_hash': hashed_pw,
                    'full_name': name,
                    'phone': client_phone,
                    'recovery_key': key
                }))
                
                if insert_res.data:
                    client_id = insert_res.data[0]['id']
                
                # Mark audit request as registered
                safe_execute(supabase_admin.table('audit_requests').update({'is_registered': True}).eq('email', email))
                flash("Protocol Initialized. Account Secured.", "success")

            # Finalize Session
            if client_id:
                session.pop('temp_client_email', None)
                session.pop('temp_client_key', None)
                session['client_access'] = True
                session['client_id'] = client_id # CRITICAL: ID is now available for Chat API
                session['client_email'] = email
            
                return redirect(url_for('public.client_dashboard'))
            else:
                flash("Error: Could not retrieve secure ID. Please contact support.", "error")
                return redirect(url_for('auth.client_access'))
            
        except Exception as e:
            print(f"Setup Error: {e}")
            flash("Database Write Error.", "error")

    return render_template('client/client_setup.html')

@auth_bp.route('/logout')
def logout():
    logout_user()
    session.clear() 
    flash('Session Terminated.', 'info')
    return redirect(url_for('auth.client_access'))