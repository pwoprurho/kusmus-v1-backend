# routes/sandbox.py
import json
import os
from flask import Blueprint, request, jsonify, session, render_template, redirect, Response, stream_with_context
from utils import role_required
# routes/sandbox.py
from core.engine import KusmusAIEngine
from core.security import sign_forensic_trace
from services.personas import DEMO_REGISTRY
from services.vanguard import calculate_vanguard_score, get_security_posture, get_latency_metrics
from services.vanguard import get_threat_level
from services.mcp_tools import MCP_TOOLKIT, get_ticker_news, get_ticker_history, get_ticker_insider_trades
import pandas as pd
import numpy as np
import datetime
from db import supabase_admin, safe_execute
from services.research_agent import ResearchKusBotService

sandbox_bp = Blueprint('sandbox', __name__)




@sandbox_bp.route("/investor")
@role_required('client', 'admin') # Allow both clients and admins
def investor_dashboard():
    """Renders the Sovereign Vault (Market Sentinel) interface."""
    return render_template('client/investor.html')
@sandbox_bp.route("/api/news/<ticker>")
def api_ticker_news(ticker):
    """API endpoint to get live news for a ticker."""
    try:
        news = get_ticker_news(ticker)
        return jsonify({"ticker": ticker, "news": news})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@sandbox_bp.route("/api/insider/<ticker>")
def api_ticker_insider(ticker):
    """API endpoint to get live insider trades for a ticker."""
    try:
        data = get_ticker_insider_trades(ticker)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def calculate_rsi_manual(prices, period=14):
    """Calculate RSI without pandas_ta."""
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

@sandbox_bp.route("/sandbox")
def sandbox_view():
    """
    Handles the transition from select_demo to the actual sandbox.
    [LIBERALIZED] Mobile gate and session restrictions removed.
    """
    # 2. DEMO VALIDATION & RESOLUTION
    short_map = {
        'sentinel': 'sentinel_monitor',
        'robotics': 'surge_vla'
    }

    selected_demo = request.args.get('demo', '')

    # --- MOBILE GATE ENFORCEMENT ---
    ua = request.headers.get('User-Agent', '').lower()
    is_mobile = any(x in ua for x in ['iphone', 'android', 'blackberry', 'windows phone'])
    # Only block if it's NOT desktop mode (some mobile browsers can trick this)
    # but we'll stick to a simple UA check for now as requested.
    if is_mobile:
        return render_template("demo_mobile.html")

    # If no demo selected, show the selector
    if not selected_demo:
        return render_template("select_demo.html", demos=DEMO_REGISTRY)

    # SPECIAL CASE: Tax Agent Demo
    if 'tax' in selected_demo.lower() or 'compliance' in selected_demo.lower():
        # If user selected a specific filing type, go straight to the Tax Agent UI
        if 'personal' in selected_demo.lower():
            session['tax_filing_type'] = 'personal'
            return render_template('client/tax_agent.html', is_sandbox_demo=True, filing_type='personal', user=session.get('user', {}))
        elif 'corporate' in selected_demo.lower():
            session['tax_filing_type'] = 'corporate'
            return render_template('client/tax_agent.html', is_sandbox_demo=True, filing_type='corporate', user=session.get('user', {}))
        else:
            # Show the filing type selection screen first
            return render_template('tax_select.html')

    # SPECIAL CASE: Market Sentinel / Investor Demo
    if 'market' in selected_demo.lower() or 'investor' in selected_demo.lower() or 'sentinel_equity' in selected_demo.lower():
        # Render the investor template in Sandbox/Demo mode
        return render_template('client/investor.html', is_sandbox_demo=True)

    # SPECIAL CASE: Deep Research kus_bot
    if 'research' in selected_demo.lower() or 'planner' in selected_demo.lower():
        return render_template('client/research_agent.html', user=session.get('user', {}))

    # SPECIAL CASE: Physics Sandbox
    if 'physics' in selected_demo.lower() or 'stem' in selected_demo.lower():
        return render_template('stem.html', is_sandbox_demo=True)

    def resolve_demo_key(raw):
        if not raw:
            return 'sentinel_monitor'
        if raw in DEMO_REGISTRY:
            return raw
        if raw in short_map:
            return short_map[raw]
        # sanitize: allow only alphanumeric and underscore
        safe = ''.join(c for c in raw if c.isalnum() or c == '_')
        return short_map.get(safe, 'sentinel_monitor')

    backend_id = resolve_demo_key(selected_demo)

    # Store in session for the API chat route to reference
    session['active_demo_id'] = backend_id
    session['v_score'] = 100

    # Retrieve full demo object to pass to template (So template doesn't need to guess names)
    demo_info = DEMO_REGISTRY.get(backend_id, DEMO_REGISTRY['sentinel_monitor'])

    return render_template('sandbox.html', demo_key=backend_id, demo=demo_info)


@sandbox_bp.route('/api/stem/fix', methods=['POST'])
def stem_fix():
    data = request.get_json() or {}
    failed_code = data.get('failed_code')
    error_msg = data.get('error_msg')
    subject = data.get('subject', 'physics')
    
    if not failed_code or not error_msg:
        return jsonify({'error': 'Failed code and error message required'}), 400
        
    engine = StemAIEngine()
    result = engine.fix_simulation(failed_code, error_msg, subject_name=subject)
    return jsonify({'success': True, 'result': result})

@sandbox_bp.route("/api/sandbox/chat_stream", methods=["POST"])
def sandbox_chat_stream():
    try:
        data = request.get_json() or {}
        demo_id = data.get('demo_id') or session.get('active_demo_id', 'sentinel_monitor')
        user_message = data.get('message', '').strip()
        context_logs = data.get('context_logs', [])

        persona = DEMO_REGISTRY.get(demo_id, DEMO_REGISTRY['sentinel_monitor'])

        # --- SOVEREIGN AUTO-ROUTE ---
        client_id = session.get('client_id')
        sovereign_config = {}
        if client_id:
            from services.sovereign_node import SovereignNodeManager
            node = SovereignNodeManager.get_client_node(client_id)
            if node and node['status'] == 'active' and node.get('node_url'):
                sovereign_config = {
                    "api_key": node['api_key'],
                    "base_url": f"{node['node_url']}/v1" # Standard OpenAI/vLLM path
                }

        engine = KusmusAIEngine(
            system_instruction=persona['instruction'],
            model_name=persona.get('model', 'gemini-2.5-flash-lite'),
            **sovereign_config
        )

        def generate():
            full_response_text = ""
            collected_thoughts = []
            has_content = False
            
            # Stream events from the engine
            for event in engine.generate_response_stream(user_message, context_logs=context_logs):
                # Capture thoughts for fallback and mitigation analysis
                if event.get('type') == 'thought':
                    collected_thoughts.append(event.get('content', ''))

                # Always yield the event to the frontend (Thought Trace depends on this)
                yield f"data: {json.dumps(event)}\n\n"
                
                if event.get('type') == 'content':
                    full_response_text += event.get('content', '')
                    has_content = True
            
            # Fallback: If no direct content was produced (common with Thinking models),
            # synthesize a response from the thoughts so the user sees *something* in the main chat.
            if not has_content:
                if collected_thoughts:
                    # Present the thoughts as a structured analysis report
                    fallback_msg = "### Cognitive Analysis Report\n\n" + "\n\n".join(collected_thoughts)
                else:
                    fallback_msg = " [Analysis concluded with no textual output. Check telemetry logs.]"
                
                # Send this as content so it appears in the main bubble
                yield f"data: {json.dumps({'type': 'content', 'content': fallback_msg})}\n\n"
                full_response_text = fallback_msg

                # SYSTEM OVERRIDE: If user requested mitigation but AI failed to execute tool, force it.
                if "self-heal" in user_message.lower() or "mitigate" in user_message.lower():
                     try:
                         # Simulate System Override
                         override_thought = "SYSTEM OVERRIDE: Detecting stalled mitigation protocol. Auto-executing Vanguard defense."
                         yield f"data: {json.dumps({'type': 'thought', 'content': override_thought})}\n\n"
                         collected_thoughts.append(override_thought)

                         if "perform_self_heal" in MCP_TOOLKIT:
                             result = MCP_TOOLKIT["perform_self_heal"]("System_Override_Target")
                             output_md = f"\n\n**Vanguard Protocol Executed (Override):**\n```json\n{json.dumps(result, indent=2)}\n```\n"
                             
                             yield f"data: {json.dumps({'type': 'content', 'content': output_md})}\n\n"
                             full_response_text += output_md
                     except Exception as e:
                         pass

            # Post-generation logic to maintain demo state
            # Check BOTH the final text and the thoughts for success indicators
            combined_text = (full_response_text + "\n" + "\n".join(collected_thoughts)).upper()
            is_mitigated = any(x in combined_text for x in ["SUCCESS", "MITIGATED", "NEUTRALIZED", "RESOLVED"])
            
            current_score = session.get('v_score', 100)
            
            # Rehydrate logs if needed or just use passed checks
            new_score = calculate_vanguard_score(current_score, context_logs, is_mitigated)
            session['v_score'] = new_score
            threat_level = get_threat_level(new_score, context_logs)
            posture = get_security_posture(new_score)
            latency = get_latency_metrics(context_logs, is_mitigated)

            meta_data = {
                "type": "meta",
                "v_score": new_score,
                "threat_level": threat_level,
                "status": posture,
                "latency": latency,
                "demo_log": None
            }
             
            if 'log_signature' in persona:
                 ts = datetime.datetime.utcnow().strftime('%H:%M:%S')
                 meta_data['demo_log'] = f"[{ts}] {persona['log_signature']}"

            yield f"data: {json.dumps(meta_data)}\n\n"
            yield "data: [DONE]\n\n"

        return Response(stream_with_context(generate()), mimetype='text/event-stream')

    except Exception as e:
        print(f"Sandbox Stream Error: {e}")
        error_msg = str(e) if os.getenv('FLASK_ENV') == 'development' else "An internal error occurred during neural transmission."
        return jsonify({'error': error_msg}), 500


@sandbox_bp.route("/api/sandbox/chat", methods=["POST"])
def sandbox_chat():
    thought_trace = []
    response_text = ""
    demo_id = "unknown"
    
    try:
        data = request.get_json()
        # Use session-stored ID if not provided in JSON
        demo_id = data.get('demo_id') or session.get('active_demo_id', 'sentinel_monitor')
        user_message = data.get('message', '').strip()
        context_logs = data.get('context_logs', [])

        persona = DEMO_REGISTRY.get(demo_id, DEMO_REGISTRY['sentinel_monitor'])

        # --- SOVEREIGN AUTO-ROUTE ---
        client_id = session.get('client_id')
        sovereign_config = {}
        if client_id:
            from services.sovereign_node import SovereignNodeManager
            node = SovereignNodeManager.get_client_node(client_id)
            if node and node['status'] == 'active' and node.get('node_url'):
                sovereign_config = {
                    "api_key": node['api_key'],
                    "base_url": f"{node['node_url']}/v1"
                }

        user_message_aug = user_message

        engine = KusmusAIEngine(
            system_instruction=persona['instruction'],
            model_name=persona.get('model', 'gemini-2.5-flash-lite'),
            **sovereign_config
        )

        response_text, thought_trace = engine.generate_response(user_message_aug, context_logs=context_logs)

        # Build a demo-specific log entry using persona log signature if present
        demo_log = None
        if 'log_signature' in persona:
            ts = datetime.datetime.utcnow().strftime('%H:%M:%S')
            demo_log = f"[{ts}] {persona['log_signature']}"
            # append to session context logs for continuity
            context_logs.append(demo_log)
            # keep only recent 50
            session['context_logs'] = context_logs[-50:]

        is_mitigated = any(x in response_text.upper() for x in ["SUCCESS", "MITIGATED", "NEUTRALIZED"])

        current_score = session.get('v_score', 100)
        new_score = calculate_vanguard_score(
            current_score=current_score,
            context_logs=context_logs,
            is_mitigated=is_mitigated
        )
        session['v_score'] = new_score
        threat_level = get_threat_level(new_score, context_logs)

        # Decide on self-heal: always run when vanguard score drops below 50,
        # and also run after positive mitigation when posture indicates secured.
        self_heal_result = None
        posture = get_security_posture(new_score)
        
        latency = get_latency_metrics(context_logs, is_mitigated)

        # Always trigger self-heal automatically if score indicates high risk
        if new_score < 50:
            try:
                from services.mcp_tools import perform_self_heal
                self_heal_result = perform_self_heal(demo_id)
            except Exception:
                self_heal_result = {'status': 'FAILED', 'actions': []}

            # Append self-heal summary to logs and session
            if self_heal_result:
                sh_log = f"[{datetime.datetime.utcnow().strftime('%H:%M:%S')}] [AUTO_SELF_HEAL_LOW_VS] {self_heal_result.get('status')}"
                context_logs.append(sh_log)
                session['context_logs'] = context_logs[-200:]

        # Also run self-heal after mitigation if posture indicates secured
        elif is_mitigated and (new_score >= 90 or posture.startswith('SECURED')):
            try:
                self_heal_result = perform_self_heal(demo_id)
                if self_heal_result:
                    sh_log = f"[{datetime.datetime.utcnow().strftime('%H:%M:%S')}] [SELF_HEAL] {self_heal_result.get('status')}"
                    context_logs.append(sh_log)
                    session['context_logs'] = context_logs[-200:]
            except Exception:
                self_heal_result = {'status': 'FAILED', 'actions': []}

        # Persist telemetry immediately (signed) and ALWAYS append to local file.
        telemetry_saved = False
        wrote_local = False
        try:
            sig, signed_payload = sign_forensic_trace(thought_trace, user_message)
            telemetry_record = {
                'demo_id': demo_id,
                'demo_log': demo_log,
                'thought_trace': json.dumps(thought_trace),
                'context_logs': json.dumps(context_logs),
                'v_score': new_score,
                'threat_level': threat_level,
                'signature': sig,
                'signed_payload': json.dumps(signed_payload),
                'client_ts': data.get('client_send_ts'),
                'rtt': None,
                'self_heal': json.dumps(self_heal_result) if self_heal_result else None,
                'created_at': datetime.datetime.utcnow().isoformat()
            }
            
            if supabase_admin:
                try:
                    safe_execute(supabase_admin.table('sandbox_telemetry').insert(telemetry_record))
                    telemetry_saved = True
                except Exception:
                    telemetry_saved = False

            # Always append to local file as a durable fallback and audit trail.
            try:
                os.makedirs('data', exist_ok=True)
                # prefix each local telemetry line with demo_id to make grepping by target easier
                with open('data/sandbox_telemetry.log', 'a', encoding='utf-8') as f:
                    f.write(f"{demo_id} " + json.dumps(telemetry_record) + '\n')
                wrote_local = True
            except Exception:
                wrote_local = False

        except Exception:
            telemetry_saved = False
            wrote_local = False

        return jsonify({
            'response': response_text,
            'thought_trace': thought_trace,
            'demo_log': demo_log,
            'self_heal': self_heal_result,
            'v_score': new_score,
            'threat_level': threat_level,
            'status': get_security_posture(new_score),
            'latency': latency,
            'telemetry_saved': telemetry_saved,
            'telemetry_written_local': wrote_local
        })

    except Exception as e:
        # LOG GENERIC/CRITICAL ERRORS TO FILE
        error_msg = f"CRITICAL_SYSTEM_FAILURE: {str(e)}"
        thought_trace.append(error_msg)
        
        try:
            os.makedirs('data', exist_ok=True)
            timestamp = datetime.datetime.utcnow().isoformat()
            
            # 1. Log to Telemetry
            with open('data/sandbox_telemetry.log', 'a', encoding='utf-8') as f:
                err_record = {
                    'timestamp': timestamp,
                    'demo_id': demo_id,
                    'error': str(e),
                    'thought_trace': json.dumps(thought_trace)
                }
                f.write(f"{demo_id} [ERROR] {json.dumps(err_record)}\n")
            
            # 2. Log to Forensic Memory (log.txt)
            with open('data/log.txt', 'a', encoding='utf-8') as f:
                f.write(f"[{timestamp}] [SYSTEM_ERROR] {demo_id}: {str(e)}\n")
                
        except Exception:
            pass

        return jsonify({
            'response': "An internal system error occurred. Our team has been notified.", 
            'thought_trace': thought_trace,
            'error': 'internal_error'
        }), 500



@sandbox_bp.route('/api/sandbox/telemetry', methods=['POST'])
def persist_telemetry():
    """Persist telemetry (thought_trace, logs, v_score, threat_level) to Supabase or local file fallback."""
    try:
        payload = request.get_json() or {}
        demo_id = payload.get('demo_id') or session.get('active_demo_id', 'sentinel_monitor')
        user_message = payload.get('user_message', '')
        thought_trace = payload.get('thought_trace', [])
        context_logs = payload.get('context_logs', [])
        v_score = payload.get('v_score')
        threat_level = payload.get('threat_level')
        client_ts = payload.get('client_send_ts')
        rtt = payload.get('rtt')
        demo_log = payload.get('demo_log')
        self_heal = payload.get('self_heal')

        # Create tamper-proof signature for reasoning
        signature, signed_payload = sign_forensic_trace(thought_trace, user_message)

        record = {
            'demo_id': demo_id,
            'demo_log': demo_log,
            'thought_trace': json.dumps(thought_trace),
            'context_logs': json.dumps(context_logs),
            'v_score': v_score,
            'threat_level': threat_level,
            'signature': signature,
            'signed_payload': json.dumps(signed_payload),
            'client_ts': client_ts,
            'rtt': rtt,
            'self_heal': json.dumps(self_heal) if self_heal else None,
            'created_at': datetime.datetime.utcnow().isoformat()
        }

        # import supabase client lazily to avoid circular import with app

        # Try to insert to Supabase if available; always append locally as well.
        try:
            if supabase_admin:
                try:
                    safe_execute(supabase_admin.table('sandbox_telemetry').insert(record))
                except Exception:
                    pass
        except Exception:
            pass

        try:
            os.makedirs('data', exist_ok=True)
            # prefix each local telemetry line with demo_id for quick identification
            with open('data/sandbox_telemetry.log', 'a', encoding='utf-8') as f:
                f.write(f"{record.get('demo_id','unknown')} " + json.dumps(record) + '\n')
        except Exception:
            # nothing more we can do here; return success to caller
            pass

        return jsonify({'status': 'ok', 'signature': signature})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@sandbox_bp.route('/api/mcp/invoke', methods=['POST'])
def invoke_mcp_tool():
    """Invoke a whitelisted MCP tool from the server-side toolkit."""
    try:
        payload = request.get_json() or {}
        tool = payload.get('tool')
        args = payload.get('args', {})
        # lazy import registry
        from services.mcp_tools import MCP_TOOLKIT
        fn = MCP_TOOLKIT.get(tool)
        if not fn:
            return jsonify({'error': 'unknown_tool', 'tool': tool}), 400

        # allow either dict kwargs or list/tuple positional args
        if isinstance(args, dict):
            result = fn(**args)
        elif isinstance(args, (list, tuple)):
            result = fn(*args)
        else:
            result = fn(args)

        # append result to session logs and return
        session_logs = session.get('context_logs', [])
        session_logs.append(f"[{datetime.datetime.utcnow().strftime('%H:%M:%S')}] TOOL:{tool} => {str(result)[:200]}")
        session['context_logs'] = session_logs[-200:]

        return jsonify({'status': 'ok', 'tool': tool, 'result': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Calendar admin endpoints moved to routes/admin.py

# --- DEEP RESEARCH kus_bot API ---
@sandbox_bp.route('/api/research/plan', methods=['POST'])
def research_plan():
    data = request.get_json() or {}
    goal = data.get('goal')
    if not goal: return jsonify({'error': 'Goal required'}), 400
    
    # Detect Sovereign Node
    client_id = session.get('client_id')
    sovereign_config = None
    if client_id:
        from services.sovereign_node import SovereignNodeManager
        node = SovereignNodeManager.get_client_node(client_id)
        if node and node['status'] == 'active' and node.get('node_url'):
            sovereign_config = {"base_url": f"{node['node_url']}/v1", "api_key": node['api_key']}

    result = ResearchKusBotService.create_plan(goal, sovereign_config=sovereign_config)
    return jsonify(result)

@sandbox_bp.route('/api/research/execute_task', methods=['POST'])
def research_execute_task():
    data = request.get_json() or {}
    plan_id = data.get('plan_id')
    task_text = data.get('task_text')
    previous_context = data.get('previous_context', '')
    
    if not plan_id or not task_text: 
        return jsonify({'error': 'Plan ID and Task Text required'}), 400
    
    # Detect Sovereign Node
    client_id = session.get('client_id')
    sovereign_config = None
    if client_id:
        from services.sovereign_node import SovereignNodeManager
        node = SovereignNodeManager.get_client_node(client_id)
        if node and node['status'] == 'active' and node.get('node_url'):
            sovereign_config = {"base_url": f"{node['node_url']}/v1", "api_key": node['api_key']}

    result = ResearchKusBotService.execute_research_task(plan_id, task_text, previous_context, sovereign_config=sovereign_config)
    return jsonify(result)

@sandbox_bp.route('/api/research/execute', methods=['POST'])
def research_execute():
    data = request.get_json() or {}
    plan_id = data.get('plan_id')
    tasks = data.get('tasks', []) # List of strings
    if not plan_id or not tasks: return jsonify({'error': 'Plan ID and Tasks required'}), 400
    
    # Detect Sovereign Node
    client_id = session.get('client_id')
    sovereign_config = None
    if client_id:
        from services.sovereign_node import SovereignNodeManager
        node = SovereignNodeManager.get_client_node(client_id)
        if node and node['status'] == 'active' and node.get('node_url'):
            sovereign_config = {"base_url": f"{node['node_url']}/v1", "api_key": node['api_key']}

    result = ResearchKusBotService.execute_research(plan_id, tasks, sovereign_config=sovereign_config)
    return jsonify(result)

@sandbox_bp.route('/api/research/report', methods=['POST'])
def research_report():
    data = request.get_json() or {}
    research_id = data.get('research_id')
    plan_id = data.get('plan_id')
    
    if not research_id and not plan_id: 
        return jsonify({'error': 'Research ID or Plan ID required'}), 400
    
    # Detect Sovereign Node
    client_id = session.get('client_id')
    sovereign_config = None
    if client_id:
        from services.sovereign_node import SovereignNodeManager
        node = SovereignNodeManager.get_client_node(client_id)
        if node and node['status'] == 'active' and node.get('node_url'):
            sovereign_config = {"base_url": f"{node['node_url']}/v1", "api_key": node['api_key']}

    result = ResearchKusBotService.generate_report(research_id, plan_id=plan_id, sovereign_config=sovereign_config)
    return jsonify(result)
