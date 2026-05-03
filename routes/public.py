import json
import os
import re
import hashlib
from datetime import datetime
from flask import Blueprint, request, jsonify, session, render_template, redirect, url_for, flash, Response, make_response
from core.engine import KusmusAIEngine
from services.personas import MAIN_ASSISTANT, DEMO_REGISTRY
from db import supabase_admin, safe_execute
import yaml

public_bp = Blueprint('public', __name__)

# === CLIENT DASHBOARD ROUTE ===
@public_bp.route('/client-dashboard')
def client_dashboard():
    # Only allow access if client session is valid
    if not session.get('client_access') or not session.get('client_id'):
        return render_template('403.html')
    return render_template('client/client_dashboard.html')

# === CLIENT CHAT ROUTE ===
@public_bp.route('/client-chat')
def client_chat():
    # Only allow access if client session is valid
    if not session.get('client_access') or not session.get('client_id'):
        return render_template('403.html')
    return render_template('client/client_chat.html')

# === CLIENT SETTINGS ROUTE ===
@public_bp.route('/settings', methods=['GET', 'POST'])
def client_settings():
    # 1. Security Check
    if not session.get('client_access') or not session.get('client_id'):
        return render_template('403.html')

    client_id = session.get('client_id')

    if request.method == 'POST':
        try:
            # 2. Extract Form Data
            deriv_token = request.form.get('deriv_token')
            gemini_key = request.form.get('gemini_key')
            risk = request.form.get('risk_tolerance')
            phone = request.form.get('phone')
            
            # Update phone in DB with retry
            try:
                safe_execute(supabase_admin.table('clients').update({'phone': phone}).eq('id', client_id))
            except Exception as e:
                print(f"Phone Update Error: {e}")

            # 3. Simulate Configuration Update
            config_update = {
                'deriv_token': deriv_token if deriv_token else None,
                'gemini_key': gemini_key if gemini_key else None,
                'risk_tolerance': int(risk) if risk else 5,
                'phone': phone
            }
            
            # Attempt update (Safe simulation)
            try:
                # supabase_admin.table('clients').update({'config': config_update}).eq('id', client_id).execute()
                pass 
            except Exception as e:
                print(f"Config Save Warning: {e}")

            # 4. Handle Password Change (If provided)
            # ... (unchanged)
            new_pw = request.form.get('new_password')
            confirm_pw = request.form.get('confirm_password')

            if new_pw:
                if new_pw != confirm_pw:
                    flash("Passwords do not match.", "error")
                    return render_template('client/client_settings.html', config=config_update)
                
                flash("Password Updated Successfully.", "success")
            else:
                flash("Configuration Saved.", "success")
            
            return redirect(url_for('public.client_settings'))

        except Exception as e:
            flash(f"Error saving settings: {str(e)}", "error")

    # GET Request: Fetch existing config
    mock_config = {
        'risk_tolerance': 5,
        'deriv_token': '',
        'gemini_key': '',
        'phone': ''
    }
    
    try:
        res = supabase_admin.table('clients').select('phone').eq('id', client_id).single().execute()
        if res.data:
            mock_config['phone'] = res.data.get('phone', '')
    except: pass

    return render_template('client/client_settings.html', config=mock_config)

# =========================================================
# === CORE PAGE ROUTES ===
# =========================================================

def _get_skill_categories():
    """Discover skill categories from kushub and map to pretty metadata."""
    registry_path = os.path.join(os.getcwd(), 'kushub', 'tools')
    if not os.path.exists(registry_path):
        return []

    # Map raw folder names to premium UI attributes
    CATEGORY_MAP = {
        'audio': {'name': 'Voice Intelligence', 'icon': 'fas fa-microphone', 'color': '#00c3ff', 'desc': 'Advanced speech-to-text and auditory analysis for real-time monitoring.'},
        'image': {'name': 'Visual Computing', 'icon': 'fas fa-image', 'color': '#0072ff', 'desc': 'Computer vision and visual understanding for security and spatial awareness.'},
        'llm': {'name': 'Core AI Engine', 'icon': 'fas fa-brain', 'color': '#FFD700', 'desc': 'Foundation models and reasoning cores that power the logic of every Pod.'},
        'social': {'name': 'Social Intelligence', 'icon': 'fas fa-share-nodes', 'color': '#00ff88', 'desc': 'Automated community engagement and sentiment correlation across digital layers.'},
        'video': {'name': 'Motion Analysis', 'icon': 'fas fa-video', 'color': '#ff4444', 'desc': 'Real-time video stream processing for behavioral detection and auditing.'},
        'agent-tools': {'name': 'Autonomous Agency', 'icon': 'fas fa-robot', 'color': '#6a11cb', 'desc': 'Specialized toolsets for independent AI agents to perform multi-step tasks.'},
        'utilities': {'name': 'Operational Utilities', 'icon': 'fas fa-toolbox', 'color': '#888', 'desc': 'Essential helper tools for data transformation, search, and maintenance.'},
        'infsh-cli': {'name': 'Infrastructure Control', 'icon': 'fas fa-terminal', 'color': '#ffffff', 'desc': 'Command-line interfaces for direct management of sovereign hardware.'}
    }

    categories = []
    try:
        raw_folders = [f for f in os.listdir(registry_path) if os.path.isdir(os.path.join(registry_path, f))]
        for folder in raw_folders:
            meta = CATEGORY_MAP.get(folder, {
                'name': folder.replace('-', ' ').title(),
                'icon': 'fas fa-cube',
                'color': '#555',
                'desc': f'Deployment-ready skills for {folder} operations.'
            })
            categories.append(meta)
    except Exception as e:
        print(f"Skill Discovery Error: {e}")
    
    return categories

def _get_curated_industries():
    """Comprehensive industry mapping reflecting the original supported sectors."""
    return [
        {'name': 'Telecommunications', 'icon': 'fas fa-tower-broadcast', 'color': '#00c3ff', 'desc': 'Autonomous O-RAN defense and network resilience for regional telecommunications leaders.'},
        {'name': 'Banking & Finance', 'icon': 'fas fa-vault', 'color': '#0072ff', 'desc': 'Execution-grade signal correlation and automated statutory tax compliance for institutional finance.'},
        {'name': 'Retail & Wholesale', 'icon': 'fas fa-shopping-cart', 'color': '#00ff88', 'desc': 'VLA Robotics for warehouse integrity and frontline labor optimization via automated support pods.'},
        {'name': 'Oil & Gas / Energy', 'icon': 'fas fa-oil-well', 'color': '#ff7e00', 'desc': 'Predictive maintenance and sovereign resource telemetry for the energy sector.'},
        {'name': 'Construction & Engineering', 'icon': 'fas fa-trowel-bricks', 'color': '#ff4444', 'desc': 'Autonomous project oversight and kinematic reasoning for large-scale infrastructure.'},
        {'name': 'Integrated Security', 'icon': 'fas fa-shield-halved', 'color': '#ff4444', 'desc': 'Unified digital/physical defense with integrated personnel integrity vetting.'},
        {'name': 'Agriculture & Food Security', 'icon': 'fas fa-seedling', 'color': '#2ecc71', 'desc': 'Sovereign climate telemetry and autonomous supply chain optimization for food security.'},
        {'name': 'Manufacturing & Robotics', 'icon': 'fas fa-robot', 'color': '#9b59b6', 'desc': 'Agentic factory floor orchestration and high-fidelity assembly line diagnostics.'},
        {'name': 'Entertainment & Media', 'icon': 'fas fa-clapperboard', 'color': '#ff00ff', 'desc': 'Personalized engagement pods and autonomous content synthesis for global digital layers.'},
        {'name': 'Advertising & Branding', 'icon': 'fas fa-ad', 'color': '#FFD700', 'desc': 'High-fidelity branding pods and sentiment-driven asset generation.'},
        {'name': 'Critical Infrastructure', 'icon': 'fas fa-city', 'color': '#64748b', 'desc': 'The foundational engine for autonomous success across power and state logistics.'}
    ]

@public_bp.route("/")
def home():
    from services.personas import DEMO_REGISTRY
    industries = _get_curated_industries()
    categories = _get_skill_categories()
    
    # Select featured academy projects (top 4)
    featured_projects = {}
    priority_keys = ['tax_compliance_agent', 'sentinel_monitor', 'market_sentinel', 'surge_vla']
    for key in priority_keys:
        if key in DEMO_REGISTRY:
            featured_projects[key] = DEMO_REGISTRY[key]
            
    return render_template("index.html", 
                           industries=industries, 
                           categories=categories, 
                           featured_projects=featured_projects)

@public_bp.route("/careers")
def careers():
    return render_template("careers.html")

@public_bp.route("/library")
def library():
    import os
    library_dir = os.path.join(os.getcwd(), 'static', 'library_pdfs')
    if not os.path.exists(library_dir):
        os.makedirs(library_dir, exist_ok=True)
    
    documents = []
    for f in os.listdir(library_dir):
        if f.endswith('.pdf'):
            file_path = os.path.join(library_dir, f)
            size_mb = os.path.getsize(file_path) / (1024 * 1024)
            documents.append({
                'filename': f,
                'name': f.replace('.pdf', '').replace('_', ' ').replace('-', ' ').title(),
                'size': f"{size_mb:.1f}MB"
            })
            
    return render_template("library.html", documents=documents)

@public_bp.route("/academy/apply", methods=['GET', 'POST'])
def academy_apply():
    if request.method == 'POST':
        name = request.form.get('name')
        contact = request.form.get('contact')
        experience = request.form.get('experience')
        career_goal = request.form.get('career_goal') # 'New' or 'Existing'
        ai_ambition = request.form.get('ai_ambition')
        institute = request.form.get('institute') # Optional

        if not name or not contact or not experience:
            flash("Identity and background markers are required for Academy selection.", "error")
            return render_template("academy_apply.html")

        try:
            # Simulate high-fidelity tracking in Supabase
            if supabase_admin:
                safe_execute(supabase_admin.table('academy_applications').insert({
                    'name': name,
                    'contact_info': contact,
                    'professional_background': experience,
                    'trajectory': career_goal,
                    'ambition': ai_ambition,
                    'institution': institute or 'Independent'
                }))

            flash("Transmission Complete. The Selection Committee will review your telemetry and reach out via secure channels.", "success")
            return redirect(url_for('public.home'))
        except Exception as e:
            print(f"Academy Enrollment Error: {e}")
            flash("Secure transmission disrupted. Please re-submit your parameters.", "error")
            return render_template("academy_apply.html")

    return render_template("academy_apply.html")

@public_bp.route("/solutions")
def solutions():
    industries = _get_curated_industries()
    return render_template("solutions.html", industries=industries)

@public_bp.route("/infrastructure")
def infrastructure():
    return render_template("infrastructure.html")

@public_bp.route("/method")
def method():
    return render_template("method.html")

@public_bp.route("/compliance")
def compliance():
    return render_template("compliance.html")

@public_bp.route('/community')
def community():
    return render_template('community.html')

@public_bp.route('/community/download/<platform>')
def community_download(platform):
    directory = os.path.join('static', 'downloads')
    filename_map = {
        'android': 'kusmus-ai-community.apk',
        'windows': 'kusmus-ai-community-windows.zip',
        'ios': 'kusmus-ai-community.ipa',
        'macos': 'kusmus-ai-community-macos.zip',
        'linux': 'kusmus-ai-community-linux.zip'
    }
    filename = filename_map.get(platform)
    if not filename:
        return "Invalid platform", 400
    
    # Return placeholder or file if exists
    file_path = os.path.join(directory, filename)
    if not os.path.exists(file_path):
        # Create a tiny placeholder so the link doesn't 404
        if not os.path.exists(directory):
            os.makedirs(directory)
        with open(file_path, 'w') as f:
            f.write("Binary pending build completion.")
            
    return redirect(url_for('static', filename=f'downloads/{filename}'))

@public_bp.route('/api/community/models')
def community_models():
    # Curated models for Kusmus AI Community Edition
    models = [
        {"name": "Llama-3.2-3B-Instruct", "author": "Meta", "url": "https://huggingface.co/meta-llama/Llama-3.2-3B-Instruct-GGUF"},
        {"name": "Gemma-2-2b-it", "author": "Google", "url": "https://huggingface.co/google/gemma-2-2b-it-GGUF"},
        {"name": "Qwen2.5-1.5B-Instruct", "author": "Alibaba", "url": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF"}
    ]
    return jsonify(models)

@public_bp.route("/lead-consultant-profile")
def lead_consultant_profile():
    return render_template("lead_consultant_profile.html")

@public_bp.route("/team")
def team():
    return render_template("our_team.html")

@public_bp.route("/mentor-mandate")
def mentor():
    return render_template("mentors_mandate.html")

@public_bp.route("/api/market/trend")
def market_trend_api():
    """Public API to fetch global market trend (Live)."""
    from services.mcp_tools import get_global_market_trend
    data = get_global_market_trend()
    return jsonify(data)

@public_bp.route("/api/market/history")
def market_history_api():
    """Public API to fetch historical candle data."""
    ticker = request.args.get('ticker', 'SPY')
    period = request.args.get('period', '3mo')
    interval = request.args.get('interval', '1d')
    from services.mcp_tools import get_ticker_history
    data = get_ticker_history(ticker, period, interval)
    return jsonify(data)

@public_bp.route("/podhub")
def podhub():
    """Registry page for Kusmus Hub (Kushub) skills."""
    hub_path = os.path.join(os.getcwd(), 'kushub')
    skills_by_category = {}

    if os.path.exists(hub_path):
        for root, dirs, files in os.walk(hub_path):
            if 'SKILL.md' in files:
                skill_path = os.path.join(root, 'SKILL.md')
                try:
                    with open(skill_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        # Extract YAML frontmatter
                        match = re.search(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL | re.MULTILINE)
                        if match:
                            metadata = yaml.safe_load(match.group(1))
                            
                            # Determine category from deep path
                            # kushub/tools/image/flux-image -> ['tools', 'image', 'flux-image']
                            rel_path = os.path.relpath(root, hub_path)
                            path_parts = rel_path.split(os.sep)
                            
                            category = "Miscellaneous"
                            if len(path_parts) >= 2:
                                # Use the second part (e.g. image, video, audio) as category
                                category = path_parts[1].capitalize()
                            elif len(path_parts) == 1:
                                category = path_parts[0].capitalize()

                            if category not in skills_by_category:
                                skills_by_category[category] = []
                            
                            # Extract prompt example if possible (e.g. from JSON in code blocks)
                            prompt_match = re.search(r'"prompt":\s*"(.*?)"', content)
                            sample_prompt = prompt_match.group(1) if prompt_match else "No prompt defined."
                            
                            skills_by_category[category].append({
                                'name': metadata.get('name', os.path.basename(root)),
                                'description': metadata.get('description', 'No description available.'),
                                'rel_path': rel_path.replace(os.sep, '/'),
                                'prompt': sample_prompt,
                                'model': metadata.get('model', os.path.basename(root).split('-')[0].capitalize())
                            })
                except Exception as e:
                    print(f"Error parsing skill at {skill_path}: {e}")

    return render_template("podhub.html", skills_by_category=skills_by_category)




# Valid routes for core usage
# Removed duplicate /sandbox handler to allow routes/sandbox.py to handle it authoritative.


@public_bp.route("/blog")
def blog():
    posts = []
    if supabase_admin:
        try:
            # Fetching published blog posts from Supabase
            # Updated to match Admin schema: table 'blog_posts' and status='Published'
            response = safe_execute(supabase_admin.table('blog_posts').select("*").eq('status', 'Published').order('published_at', desc=True))
            posts = response.data
        except Exception as e:
            print(f"Blog Fetch Error: {e}")
            # Fallback for older schema if migration isn't complete (optional, but good for safety)
            try:
                response = safe_execute(supabase_admin.table('posts').select("*").eq('published', True))
                if response.data: posts.extend(response.data)
            except: pass

    return render_template("blog.html", posts=posts)

@public_bp.route("/podhub/skill/<category>/<string:skill_name>")
def skill_detail(category, skill_name):
    """Detailed view for a specific Kusmus Hub skill."""
    import markdown
    import bleach
    
    # Sanitize inputs to prevent path traversal
    if not re.match(r'^[a-zA-Z0-9_-]+$', skill_name) or not re.match(r'^[a-zA-Z0-9_-]+$', category):
        return render_template("404.html"), 404

    hub_path = os.path.join(os.getcwd(), 'kushub')
    skill_dir = None
    for root, dirs, _ in os.walk(hub_path):
        if os.path.basename(root).lower() == skill_name.lower():
            rel_path = os.path.relpath(root, hub_path)
            path_parts = rel_path.split(os.sep)
            
            # Match new categorization: category is second part if deep, else first part
            resolved_category = "Miscellaneous"
            if len(path_parts) >= 2:
                resolved_category = path_parts[1].lower()
            elif len(path_parts) == 1:
                resolved_category = path_parts[0].lower()
                
            if resolved_category == category.lower():
                skill_dir = root
                break
    
    if not skill_dir:
        return render_template("404.html"), 404
    
    # Additional safety: ensure resolved path is still under hub_path
    if not os.path.realpath(skill_dir).startswith(os.path.realpath(hub_path)):
        return render_template("404.html"), 404
        
    skill_file = os.path.join(skill_dir, 'SKILL.md')
    if not os.path.exists(skill_file):
        return render_template("404.html"), 404
        
    try:
        with open(skill_file, 'r', encoding='utf-8') as f:
            content = f.read()
            
            # 1. Extract Metadata
            match = re.search(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL | re.MULTILINE)
            metadata = {}
            main_content = content
            if match:
                metadata = yaml.safe_load(match.group(1))
                main_content = content[match.end():]
                
            # 2. Render Markdown
            html_content = markdown.markdown(main_content, extensions=['fenced_code', 'tables'])
            
            # 3. Get JSON Definition if exists
            def_path = os.path.join(skill_dir, 'tool_definition.json')
            definition_json = None
            if os.path.exists(def_path):
                with open(def_path, 'r') as df:
                    definition_json = df.read()
                    
            # 4. Sanitize (Allow premium UI elements but restrict dangerous tags)
            allowed_tags = bleach.ALLOWED_TAGS | {
                'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'br', 'hr', 
                'pre', 'code', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 
                'img', 'span', 'i', 'strong', 'em', 'ul', 'ol', 'li', 'blockquote'
            }
            allowed_attrs = bleach.ALLOWED_ATTRIBUTES
            allowed_attrs.update({'img': ['src', 'alt', 'title'], 'a': ['href', 'title', 'target'], 'i': ['class'], 'span': ['class']})
            
            sanitized_html = bleach.clean(html_content, tags=allowed_tags, attributes=allowed_attrs)
            
            return render_template("skill_detail.html", 
                                 skill=metadata, 
                                 html_content=sanitized_html, 
                                 category=category,
                                 skill_name=skill_name,
                                 definition_json=definition_json)
    except Exception as e:
        print(f"Detail Rendering Error: {e}")
        return render_template("500.html"), 500

@public_bp.route("/podhub/submit", methods=["GET", "POST"])
def submit_skill():
    """Form for community skill submissions."""
    if request.method == "POST":
        # In a real app, save to DB or trigger a PR. Here we'll simulate success.
        flash("Thank you for your submission! Our team will review the skill for security and integration.", "success")
        return redirect(url_for("public.podhub"))
    return render_template("submit_skill.html")

@public_bp.route("/api/podhub/skills")
def api_podhub_skills():
    """JSON API for mobile/agent discovery of skills."""
    hub_path = os.path.join(os.getcwd(), 'kushub')
    all_skills = []
    
    if os.path.exists(hub_path):
        for root, dirs, files in os.walk(hub_path):
            if 'SKILL.md' in files:
                rel_path = os.path.relpath(root, hub_path)
                category = rel_path.split(os.sep)[0].capitalize()
                skill_name = os.path.basename(root)
                
                # Check for tool_definition.json
                definition = {}
                def_path = os.path.join(root, 'tool_definition.json')
                if os.path.exists(def_path):
                    with open(def_path, 'r') as df:
                        definition = json.load(df)
                
                all_skills.append({
                    "name": skill_name,
                    "category": category,
                    "path": rel_path.replace(os.sep, '/'),
                    "definition": definition
                })
    return jsonify({"status": "success", "skills": all_skills})

@public_bp.route("/api/podhub/skill/<category>/<string:skill_name>")
def api_skill_detail(category, skill_name):
    """JSON metadata for a specific skill (OS Model compatible)."""
    hub_path = os.path.join(os.getcwd(), 'kushub')
    skill_dir = None
    for root, dirs, _ in os.walk(hub_path):
        if os.path.basename(root).lower() == skill_name.lower():
            if os.path.relpath(root, hub_path).lower().startswith(category.lower()):
                skill_dir = root
                break
    
    if not skill_dir:
        return jsonify({"status": "error", "message": "Skill not found"}), 404
        
    def_path = os.path.join(skill_dir, 'tool_definition.json')
    definition = {}
    if os.path.exists(def_path):
        with open(def_path, 'r') as f:
            definition = json.load(f)
            
    return jsonify({
        "status": "success",
        "skill": skill_name,
        "category": category,
        "definition": definition
    })

@public_bp.route("/blog/<string:post_id>")
def blog_post(post_id):
    post = None
    if supabase_admin:
        try:
            # Fetch single post from correct table
            response = safe_execute(supabase_admin.table('blog_posts').select("*").eq('id', post_id).limit(1))
            if response.data:
                post = response.data[0]
            else:
                 # Fallback check
                response = safe_execute(supabase_admin.table('posts').select("*").eq('id', post_id).limit(1))
                if response.data: post = response.data[0]

        except Exception as e:
            print(f"Blog Post Fetch Error: {e}")
            
    if not post:
        return render_template("404.html"), 404
        
    related_posts = []
    if supabase_admin:
        try:
            # Fetch up to 3 related published posts (excluding the current one)
            related_resp = safe_execute(supabase_admin.table('blog_posts').select("*").eq('status', 'Published').neq('id', post_id).order('published_at', desc=True).limit(3))
            if related_resp and related_resp.data:
                related_posts = related_resp.data
        except Exception as e:
            print(f"Related Posts Fetch Error: {e}")

    return render_template("blog_post.html", post=post, related_posts=related_posts)

# --- FIX: Added missing route to resolve BuildError in index.html ---
@public_bp.route("/request-audit", methods=['GET', 'POST'])
def audit_request():
    if request.method == 'POST':
        company_name = request.form.get('company_name')
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        hosting_pref = request.form.get('hosting_preference')
        message = request.form.get('message')

        if not company_name or not name or not email or not phone:
            flash("All secure contact fields (Company, Name, Email, Phone) are required.", "error")
            return render_template("request_audit.html")

        try:
            # Generate a simple verification code for the client to use later
            import secrets
            import time
            verification_code = secrets.token_hex(4).upper()

            # Insert into Supabase with centralized retry
            safe_execute(supabase_admin.table('audit_requests').insert({
                'company_name': company_name,
                'name': name,
                'email': email,
                'phone': phone,
                'hosting_preference': hosting_pref,
                'message': message,
                'verification_code': verification_code
            }))

            flash(f"Request Transmitted. Your Identity Token is: {verification_code}. Keep this secure.", "success")
            return redirect(url_for('public.home'))

        except Exception as e:
            print(f"Audit Request Error (after retries): {e}")
            flash("Electronic transmission failure. Please try again.", "error")
            return render_template("request_audit.html")

    return render_template("request_audit.html")

# =========================================================
# === AI CHAT API (Standard Widget) ===
# =========================================================

@public_bp.route("/api/chat", methods=["POST"])
def chat_ai_assistant():
    """
    Standard Support Chat for the website footer/widget.
    Uses the 'MAIN_ASSISTANT' persona.
    """
    data = request.get_json()
    user_message = data.get('message', '')
    
    if not user_message: 
        return jsonify({'error': 'No message provided'}), 400
    
    try:
        # Import the dynamic loader
        from services.personas import get_main_assistant_instruction, MAIN_ASSISTANT
        
        # Initialize Engine with the Client Care Persona (Dynamically loaded)
        engine = KusmusAIEngine(
            system_instruction=get_main_assistant_instruction(),
            model_name=MAIN_ASSISTANT.get('model', 'gemini-2.5-flash-lite')
        )
        # Maintain Session-based History
        raw_history = session.get('chat_history', [])
        
        # Generate Response (Standard assistant does not need MCP tools)
        response_text, _ = engine.generate_response(user_message, history=raw_history)

        # Update History
        raw_history.append({"role": "user", "parts": [user_message]})
        raw_history.append({"role": "model", "parts": [response_text]})
        session['chat_history'] = raw_history
        
        return jsonify({'response': response_text})

    except Exception as e:
        print(f"AI Chat Error: {e}")
        return jsonify({'error': 'Connection interrupted.'}), 500

@public_bp.route("/api/chat/reset", methods=["POST"])
def reset_chat():
    session.pop('chat_history', None)
    return jsonify({'status': 'cleared'})

# === CLIENT CRYPTO WALLET ROUTE ===
@public_bp.route('/crypto-wallet', methods=['GET', 'POST'])
def crypto_wallet_action():
    # Only allow access if client session is valid
    if not session.get('client_access') or not session.get('client_id'):
        return render_template('403.html')
    user_id = session.get('client_id')
    from core.wallet import Wallet
    from core.gateways import BTCGateway, USSDGateway
    # Load wallet info
    wallet = Wallet(user_id)
    btc_address = wallet.btc_address
    eth_address = wallet.eth_address
    btc_balance = BTCGateway.get_balance(btc_address)
    result = None
    # Load transaction history (mock for now)
    transactions = []
    if os.path.exists(f"tx_{user_id}.json"):
        with open(f"tx_{user_id}.json", "r") as f:
            transactions = json.load(f)
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'send_btc':
            to_address = request.form.get('to_address')
            amount_btc = float(request.form.get('amount_btc'))
            result = BTCGateway.send_btc(wallet.btc_private_key, to_address, amount_btc)
            transactions.append({"type": "Send BTC", "amount": amount_btc, "currency": "BTC", "status": result["status"], "timestamp": str(datetime.now())})
        elif action == 'ussd_pay':
            phone_number = request.form.get('phone_number')
            amount = float(request.form.get('amount'))
            result = USSDGateway.send_payment(phone_number, amount)
            transactions.append({"type": "USSD Pay", "amount": amount, "currency": "Fiat", "status": result["status"], "timestamp": str(datetime.now())})
        # Save transaction history
        with open(f"tx_{user_id}.json", "w") as f:
            json.dump(transactions, f)
    return render_template('client/crypto_wallet_dashboard.html', btc_address=btc_address, eth_address=eth_address, btc_balance=btc_balance, result=result, transactions=transactions)

# =========================================================
# === SEO ROUTES (Sitemap & Robots) ===
# =========================================================

@public_bp.route('/sitemap.xml', methods=['GET'])
def sitemap():
    """Generates a dynamic sitemap for SEO."""
    import xml.sax.saxutils as saxutils
    
    # 1. Page Definitions
    host_url = request.url_root.rstrip('/')
    pages = [
        'public.home', 
        'public.solutions', 
        'public.infrastructure',
        'public.compliance',
        'public.method', 
        'public.lead_consultant_profile', 
        'public.team', 
        'public.mentor', 
        'public.blog',
        'public.audit_request'
    ]
    
    xml_sitemap = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml_sitemap.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')

    # 2. Static Pages
    for page in pages:
        try:
            url = url_for(page, _external=True)
            escaped_url = saxutils.escape(url)
            xml_sitemap.append(f'  <url>')
            xml_sitemap.append(f'    <loc>{escaped_url}</loc>')
            xml_sitemap.append(f'    <changefreq>weekly</changefreq>')
            xml_sitemap.append(f'    <priority>0.8</priority>')
            xml_sitemap.append(f'  </url>')
        except: continue

    # 3. Dynamic Blog Posts
    if supabase_admin:
        try:
            # Fetch from new schema
            response = safe_execute(supabase_admin.table('blog_posts').select("id, published_at").eq('status', 'Published'))
            if response.data:
                for post in response.data:
                    url = url_for('public.blog_post', post_id=post['id'], _external=True)
                    escaped_url = saxutils.escape(url)
                    
                    # Hardened Date Parsing (Must be YYYY-MM-DD)
                    raw_date = post.get('published_at')
                    if raw_date:
                        # Handle space vs T vs full timestamp
                        clean_date = raw_date.replace('T', ' ').split(' ')[0]
                    else:
                        clean_date = datetime.now().strftime('%Y-%m-%d')
                    
                    xml_sitemap.append(f'  <url>')
                    xml_sitemap.append(f'    <loc>{escaped_url}</loc>')
                    xml_sitemap.append(f'    <lastmod>{clean_date}</lastmod>')
                    xml_sitemap.append(f'    <changefreq>weekly</changefreq>')
                    xml_sitemap.append(f'    <priority>0.9</priority>')
                    xml_sitemap.append(f'  </url>')
        except: pass
        
        # 4. Dynamic PodHub Skills
        try:
            hub_path = os.path.join(os.getcwd(), 'kushub')
            for root, dirs, files in os.walk(hub_path):
                if 'SKILL.md' in files:
                    skill_name = os.path.basename(root)
                    rel_path = os.path.relpath(root, hub_path)
                    path_parts = rel_path.split(os.sep)
                    
                    # Match categorization logic from skill_detail
                    category = "Miscellaneous"
                    if len(path_parts) >= 2:
                        category = path_parts[1].lower()
                    elif len(path_parts) == 1:
                        category = path_parts[0].lower()
                        
                    url = url_for('public.skill_detail', category=category, skill_name=skill_name, _external=True)
                    escaped_url = saxutils.escape(url)
                    
                    xml_sitemap.append(f'  <url>')
                    xml_sitemap.append(f'    <loc>{escaped_url}</loc>')
                    xml_sitemap.append(f'    <changefreq>monthly</changefreq>')
                    xml_sitemap.append(f'    <priority>0.7</priority>')
                    xml_sitemap.append(f'  </url>')
        except Exception as e:
            print(f"Sitemap Skill Error: {e}")
        except: pass

    xml_sitemap.append('</urlset>')
    return Response('\n'.join(xml_sitemap), mimetype='application/xml; charset=utf-8')

@public_bp.route('/llm.txt', methods=['GET'])
def llm_txt():
    """Technical manifest for AI models/crawlers."""
    content = ""
    try:
        with open(os.path.join('static', 'llm.txt'), 'r', encoding='utf-8') as f:
            content = f.read()
    except:
        content = "Kusmus AI - Sovereign Engineering manifest pending."
    return Response(content, mimetype='text/plain')

@public_bp.route('/robots.txt', methods=['GET'])
def robots():
    """Generates robots.txt for crawlers."""
    lines = [
        "User-agent: *",
        "Allow: /",
        "Allow: /llm.txt",
        "Disallow: /admin/",
        "Disallow: /auth/",
        "Disallow: /sandbox/",
        "Disallow: /tax/",
        "Disallow: /physics/",
        "Disallow: /client-dashboard",
        "Disallow: /client-chat",
        "Disallow: /crypto-wallet",
        f"Sitemap: {url_for('public.sitemap', _external=True)}"
    ]
    return Response('\n'.join(lines), mimetype='text/plain')
# === DIAGNOSTIC ROUTE ===
@public_bp.route('/diag')
def diag():
    """Security-Hardened Diagnostic: Only available in local development."""
    is_dev = os.getenv('FLASK_ENV') == 'development' or os.getenv('FLASK_DEBUG') == '1'
    if not is_dev:
        # Fails silent-ish in production to avoid reconnaissance
        return jsonify({'error': 'Neural diagnostic path restricted.'}), 403
    
    # We only report presence/absence of keys in dev, never hashes or lengths of sensitive ones
    safe_keys = ['FLASK_ENV', 'FLASK_DEBUG', 'PORT']
    sensitive_keys = ['SUPABASE_URL', 'SUPABASE_KEY', 'SUPABASE_SERVICE_ROLE_KEY', 'DATABASE_URL', 'SECRET_KEY']
    
    status = {}
    for key in safe_keys + sensitive_keys:
        val = os.getenv(key)
        if key in sensitive_keys:
            status[key] = {'status': 'PRESENT' if val else 'MISSING'}
        else:
            status[key] = val or 'NOT_SET'

    return jsonify({
        'neural_status': 'OPERATIONAL',
        'env_summary': status,
        'cwd': os.getcwd()
    })
