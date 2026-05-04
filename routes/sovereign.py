# routes/sovereign.py
"""
Sovereign Intelligence API Routes
Provides OpenAI-compatible proxy endpoints and node management for enterprise clients.
"""

import json
from flask import Blueprint, request, jsonify, session, Response, stream_with_context
from services.sovereign_node import SovereignNodeManager
from services.skill_executor import skill_executor

sovereign_bp = Blueprint('sovereign', __name__, url_prefix='/sovereign')
node_mgr = SovereignNodeManager()


def init_csrf_exemptions(csrf):
    """
    Exempt the OpenAI-compatible proxy endpoint from CSRF protection.
    This is required because external tools (Cursor, Lovable, etc.) authenticate
    via Bearer token, not browser sessions with CSRF cookies.
    """
    csrf.exempt(sovereign_bp)


# =========================================================
# === CLIENT-FACING ENDPOINTS ===
# =========================================================

@sovereign_bp.route('/status', methods=['GET'])
def node_status():
    """
    Returns the current client's sovereign node status.
    Requires client session authentication.
    """
    client_id = session.get('client_id')
    if not client_id:
        return jsonify({"error": "Authentication required"}), 401

    node = node_mgr.get_client_node(client_id)
    if not node:
        return jsonify({
            "provisioned": False,
            "message": "No sovereign node has been provisioned for your account. Contact your account manager to get started."
        })

    # If the node is currently provisioning and has a pod_id, 
    # try to sync its status from RunPod in real-time.
    if node.get('status') == 'provisioning' and node.get('pod_id'):
        node_mgr.sync_node_status(client_id)
        # Re-fetch updated node data
        node = node_mgr.get_client_node(client_id)

    # Perform live health check
    health = node_mgr.check_node_health(node['node_url'])

    # Add pricing info
    from services.model_config import MODEL_CONFIGS
    current_specs = MODEL_CONFIGS.get(node['model_name'], {})
    
    return jsonify({
        "provisioned": True,
        "status": node['status'],
        "hosting_type": node.get('hosting_type', 'Managed'),
        "model": node['model_name'],
        "storage_gb": float(node.get('storage_gb', 0)),
        "api_key": _mask_key(node['api_key']),
        "base_url": f"/sovereign/v1/chat/completions",
        "health": health,
        "created_at": node.get('created_at'),
        "estimated_cost_hr": current_specs.get("estimated_cost_hr", 0),
        "model_configs": MODEL_CONFIGS
    })


@sovereign_bp.route('/regenerate-key', methods=['POST'])
def regenerate_key():
    """Regenerate the API key for the current client's sovereign node."""
    client_id = session.get('client_id')
    if not client_id:
        return jsonify({"error": "Authentication required"}), 401

    result = node_mgr.regenerate_api_key(client_id)
    if result['success']:
        return jsonify({
            "success": True,
            "api_key": result['api_key'],
            "message": "API key regenerated. Update your integrations with the new key."
        })
    return jsonify({"error": result.get('error', 'Failed to regenerate key')}), 400


@sovereign_bp.route('/reveal-key', methods=['GET'])
def reveal_key():
    """Reveal the full API key for the current client (authenticated only)."""
    client_id = session.get('client_id')
    if not client_id:
        return jsonify({"error": "Authentication required"}), 401

    node = node_mgr.get_client_node(client_id)
    if not node:
        return jsonify({"error": "No node provisioned"}), 404

    return jsonify({"api_key": node['api_key']})


@sovereign_bp.route('/switch-model', methods=['POST'])
def switch_model():
    """Trigger a model swap for the current client's node."""
    client_id = session.get('client_id')
    if not client_id:
        return jsonify({"error": "Authentication required"}), 401

    data = request.get_json()
    new_model = data.get('model')
    if not new_model:
        return jsonify({"error": "Target model name is required"}), 400

    result = node_mgr.update_node_model(client_id, new_model)
    if result['success']:
        return jsonify(result)
    return jsonify({"error": result.get('error', 'Update failed')}), 400


# =========================================================
# === OPENAI-COMPATIBLE PROXY ENDPOINT ===
# =========================================================

@sovereign_bp.route('/v1/chat/completions', methods=['POST'])
def chat_completions_proxy():
    """
    OpenAI-compatible chat completions endpoint.
    Authenticates via Bearer token (the client's sovereign API key),
    then proxies the request to their dedicated Ollama/vLLM instance.

    Usage (from Cursor, Lovable, or any OpenAI-compatible tool):
        POST /sovereign/v1/chat/completions
        Authorization: Bearer sk-kusmus-...
        Content-Type: application/json
        {
            "model": "llama3:8b",
            "messages": [{"role": "user", "content": "Hello"}]
        }
    """
    # Extract Bearer token
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return jsonify({"error": {"message": "Missing or invalid Authorization header. Use: Bearer sk-kusmus-...", "type": "auth_error"}}), 401

    api_key = auth_header.replace('Bearer ', '').strip()

    # Look up the node by API key
    node = node_mgr.get_node_by_api_key(api_key)
    if not node:
        return jsonify({"error": {"message": "Invalid API key", "type": "auth_error"}}), 401

    if node['status'] != 'active':
        return jsonify({"error": {"message": f"Node is currently '{node['status']}'. Contact support.", "type": "node_error"}}), 503

    # Parse the request body
    try:
        body = request.get_json(force=True)
    except Exception:
        return jsonify({"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}}), 400

    messages = body.get('messages', [])
    model = body.get('model', node['model_name'])
    stream = body.get('stream', False)

    if not messages:
        return jsonify({"error": {"message": "'messages' field is required", "type": "invalid_request_error"}}), 400

    # Proxy to the client's dedicated node
    result = node_mgr.proxy_chat_completion(
        node_url=node['node_url'],
        model=model,
        messages=messages,
        stream=stream
    )

    if result['success']:
        if stream and 'stream' in result:
            # Stream the response back as SSE
            def generate():
                try:
                    for line in result['stream'].iter_lines():
                        if line:
                            yield line.decode('utf-8') + '\n\n'
                except Exception as e:
                    yield f'data: {json.dumps({"error": str(e)})}\n\n'

            return Response(
                stream_with_context(generate()),
                content_type='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'X-Accel-Buffering': 'no'
                }
            )
        else:
            return jsonify(result['data'])
    else:
        return jsonify({"error": {"message": result['error'], "type": "node_error"}}), 502


@sovereign_bp.route('/execute-skill', methods=['POST'])
def execute_skill():
    """
    Agentic Bridge: Executes a Python skill on the KUSMUS backend.
    Requires Bearer token authentication (Sovereign API Key).
    """
    # 1. Auth check (Same as proxy)
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return jsonify({"error": "Missing Authorization header"}), 401
    
    api_key = auth_header.replace('Bearer ', '').strip()
    node = node_mgr.get_node_by_api_key(api_key)
    if not node:
        return jsonify({"error": "Invalid API key"}), 401

    # 2. Parse request
    data = request.get_json()
    if not data or 'skill_id' not in data:
        return jsonify({"error": "skill_id is required"}), 400
    
    skill_id = data['skill_id']
    params = data.get('params', {})

    # 3. Execute logic
    result = skill_executor.execute_skill(skill_id, params)
    
    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 500


@sovereign_bp.route('/execute-dynamic-skill', methods=['POST'])
def execute_dynamic_skill():
    """
    KUSMUS Code Interpreter: Executes raw Python code generated by the AI.
    Requires Bearer token authentication.
    """
    # 1. Auth check
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return jsonify({"error": "Missing Authorization header"}), 401
    
    api_key = auth_header.replace('Bearer ', '').strip()
    node = node_mgr.get_node_by_api_key(api_key)
    if not node:
        return jsonify({"error": "Invalid API key"}), 401

    # 2. Parse request
    data = request.get_json()
    if not data or 'code' not in data:
        return jsonify({"error": "Python code is required"}), 400
    
    code = data['code']
    params = data.get('params', {})

    # 3. Execute dynamically
    result = skill_executor.execute_dynamic_code(code, params)
    
    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 500


# =========================================================
# === ADMIN PROVISIONING ENDPOINTS ===
# =========================================================

@sovereign_bp.route('/admin/provision', methods=['POST'])
def admin_provision_node():
    """
    Admin-only: Provision a new sovereign node for a client.
    Expects JSON: { client_id, node_url, model_name?, storage_gb? }
    """
    from flask_login import current_user
    if not current_user.is_authenticated or current_user.role not in ('supa_admin', 'admin'):
        return jsonify({"error": "Admin access required"}), 403

    data = request.get_json()
    if not data or not data.get('client_id'):
        return jsonify({"error": "client_id is required"}), 400

    hosting_type = data.get('hosting_type', 'Managed')
    node_url = data.get('node_url', '')

    # Self-Hosted nodes need a URL; Managed nodes get one from RunPod
    if hosting_type == 'Self-Hosted' and not node_url:
        return jsonify({"error": "node_url is required for Self-Hosted nodes"}), 400

    result = node_mgr.provision_node(
        client_id=data['client_id'],
        node_url=node_url or None,
        model_name=data.get('model_name', 'llama3:8b'),
        storage_gb=data.get('storage_gb', 20),
        hosting_type=hosting_type
    )

    if result['success']:
        return jsonify({
            "success": True,
            "node": result['node'],
            "message": f"Sovereign node provisioned. API Key: {result['api_key']}"
        })
    return jsonify({"error": result.get('error', 'Provisioning failed')}), 400


@sovereign_bp.route('/admin/update-status', methods=['POST'])
def admin_update_status():
    """
    Admin-only: Update the status of a client's sovereign node.
    Expects JSON: { client_id, status }
    """
    from flask_login import current_user
    if not current_user.is_authenticated or current_user.role not in ('supa_admin', 'admin'):
        return jsonify({"error": "Admin access required"}), 403

    data = request.get_json()
    if not data or not data.get('client_id') or not data.get('status'):
        return jsonify({"error": "client_id and status are required"}), 400

    result = node_mgr.update_node_status(data['client_id'], data['status'])
    if result['success']:
        return jsonify({"success": True, "message": f"Node status updated to '{data['status']}'."})
    return jsonify({"error": result.get('error', 'Update failed')}), 400


# =========================================================
# === HELPERS ===
# =========================================================

def _mask_key(key: str) -> str:
    """Mask an API key for display, showing only the prefix and last 4 chars."""
    if not key or len(key) < 12:
        return "****"
    return f"{key[:12]}...{key[-4:]}"
