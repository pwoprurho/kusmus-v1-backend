# routes/hive.py
"""
KUSMUS Hive Rendezvous API
Handles discovery of sovereign nodes for the Federated Hive (GSP Protocol).
"""

import time
import random
from flask import Blueprint, jsonify, request

hive_bp = Blueprint('hive', __name__, url_prefix='/api/hive')

# In-memory node registry (In production, use Redis or a distributed DHT)
KNOWN_NODES = [
    {"id": "node-7f2a", "name": "Abuja-Node-01", "status": "online", "contribution": 1.2},
    {"id": "node-99c1", "name": "Lagos-Sovereign-Edge", "status": "online", "contribution": 4.5},
    {"id": "node-3e8d", "name": "Kano-Vault-Primary", "status": "offline", "contribution": 0.8},
]

@hive_bp.route('/nodes', methods=['GET'])
def get_nodes():
    """
    Returns a list of active sovereign nodes in the Hive.
    In V1.0, this uses a simulated registry for demonstration.
    """
    # Randomly shuffle or filter for realism
    active_nodes = [n for n in KNOWN_NODES if n['status'] == 'online']
    
    # Add some random jitter to simulation
    if random.random() > 0.8:
        new_node = {
            "id": f"node-{random.randint(1000, 9999):x}",
            "name": f"Node-Delta-{random.randint(1, 100)}",
            "status": "online",
            "contribution": round(random.uniform(0.1, 2.5), 1)
        }
        active_nodes.append(new_node)

    return jsonify({
        "nodes": active_nodes,
        "total_power": 12.4, # EXAFLOPS
        "timestamp": int(time.time())
    })

@hive_bp.route('/sync-weights', methods=['POST'])
def sync_weights():
    """
    Endpoint for GSP Weight Exchange.
    Receives encrypted gradients from a node and returns aggregated updates.
    """
    data = request.get_json()
    node_id = data.get('node_id')
    
    if not node_id:
        return jsonify({"error": "node_id required"}), 400

    print(f"[Hive] Received weight sync request from {node_id}")
    
    # Simulate processing
    time.sleep(1) 
    
    return jsonify({
        "status": "success",
        "updates_applied": True,
        "global_model_version": "v1.42.1",
        "next_sync_window": int(time.time()) + 3600 # 1 hour
    })
