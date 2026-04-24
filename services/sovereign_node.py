# services/sovereign_node.py
"""
Sovereign Node Manager — Manages dedicated LLM infrastructure for enterprise clients.
Handles health checks, API key generation, and OpenAI-compatible request proxying.
"""

import secrets
import hashlib
import hmac
import requests
import json
import os
import ipaddress
from urllib.parse import urlparse
from db import supabase_admin, safe_execute
from services.runpod_service import RunPodService

runpod = RunPodService()


class SovereignNodeManager:
    """Manages per-client sovereign LLM nodes (Ollama/vLLM instances)."""

    @staticmethod
    def _validate_url(url: str) -> bool:
        """
        Validate the node URL to prevent SSRF.
        Ensures the URL is valid, uses http/https, and does not point to internal/private IPs.
        """
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ('http', 'https'):
                return False
            
            hostname = parsed.hostname
            if not hostname:
                return False

            # Check if it's an IP address
            try:
                ip = ipaddress.ip_address(hostname)
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
                    return False
            except ValueError:
                # Not an IP, could be a hostname. 
                # In a production env, we'd resolve it and check the IP,
                # but blocking 'localhost' and '.local' is a good start.
                blocked_hostnames = ('localhost', '127.0.0.1', '0.0.0.0', '[::1]')
                if hostname.lower() in blocked_hostnames or hostname.endswith('.local'):
                    return False
            
            return True
        except Exception:
            return False


    @staticmethod
    def _hash_api_key(raw_key: str) -> str:
        """
        SHA-256 hash of an API key for storage/lookup.
        The raw key is shown once at provisioning; only the hash is persisted.
        """
        return hashlib.sha256(raw_key.encode()).hexdigest()

    @staticmethod
    def generate_api_key() -> str:
        """Generate a secure, unique API key for a client's sovereign node."""
        return f"sk-kusmus-{secrets.token_urlsafe(32)}"

    @staticmethod
    def get_client_node(client_id: str) -> dict | None:
        """Fetch the sovereign node config for a given client."""
        try:
            res = safe_execute(
                supabase_admin.table('sovereign_nodes')
                .select('*')
                .eq('client_id', client_id)
                .single()
            )
            return res.data if res.data else None
        except Exception as e:
            print(f"[Sovereign] Error fetching node for client {client_id}: {e}")
            return None

    @staticmethod
    def get_node_by_api_key(api_key: str) -> dict | None:
        """
        Fetch a sovereign node by its API key (used for proxy auth).
        Uses SHA-256 hash for DB lookup + constant-time comparison
        to prevent timing side-channel attacks.
        """
        try:
            key_hash = SovereignNodeManager._hash_api_key(api_key)

            # Primary: lookup by hash (new schema)
            res = safe_execute(
                supabase_admin.table('sovereign_nodes')
                .select('*')
                .eq('api_key_hash', key_hash)
                .single()
            )
            if res.data:
                return res.data

            # Fallback: lookup by raw key (pre-migration rows)
            # Uses constant-time comparison after DB fetch to avoid timing leaks
            res = safe_execute(
                supabase_admin.table('sovereign_nodes')
                .select('*')
                .eq('api_key', api_key)
                .single()
            )
            if res.data and hmac.compare_digest(res.data.get('api_key', ''), api_key):
                # Auto-migrate: store hash and clear raw key
                try:
                    safe_execute(
                        supabase_admin.table('sovereign_nodes')
                        .update({'api_key_hash': key_hash, 'api_key': f'migrated_{key_hash[:12]}'})
                        .eq('client_id', res.data['client_id'])
                    )
                except Exception:
                    pass  # Non-critical: migration will happen on next auth
                return res.data

            return None
        except Exception as e:
            print(f"[Sovereign] Error fetching node by API key: {e}")
            return None

    @staticmethod
    def check_node_health(node_url: str) -> dict:
        """
        Ping the Ollama /api/tags endpoint to check if the node is online
        and what models are available.
        """
        if not SovereignNodeManager._validate_url(node_url):
            return {"online": False, "error": "Invalid or restricted node URL."}

        try:
            resp = requests.get(f"{node_url}/api/tags", timeout=5)
            if resp.status_code == 200:
                models = resp.json().get('models', [])
                model_names = [m.get('name', 'unknown') for m in models]
                return {
                    "online": True,
                    "models": model_names,
                    "latency_ms": int(resp.elapsed.total_seconds() * 1000)
                }
            return {"online": False, "error": f"HTTP {resp.status_code}"}
        except requests.exceptions.Timeout:
            return {"online": False, "error": "Connection timed out"}
        except requests.exceptions.ConnectionError:
            return {"online": False, "error": "Connection refused"}
        except Exception as e:
            return {"online": False, "error": str(e)}

    @staticmethod
    def proxy_chat_completion(node_url: str, model: str, messages: list, stream: bool = False) -> dict:
        """
        Proxy an OpenAI-compatible /v1/chat/completions request to the
        client's dedicated Ollama/vLLM instance.

        Uses Ollama's OpenAI-compatible endpoint.
        """
        if not SovereignNodeManager._validate_url(node_url):
            return {"success": False, "error": "Invalid or restricted node URL."}

        try:
            payload = {
                "model": model,
                "messages": messages,
                "stream": stream
            }

            resp = requests.post(
                f"{node_url}/v1/chat/completions",
                json=payload,
                timeout=120,
                stream=stream
            )

            if resp.status_code == 200:
                if stream:
                    # Return the raw response for streaming
                    return {"success": True, "stream": resp}
                else:
                    return {"success": True, "data": resp.json()}
            else:
                return {
                    "success": False,
                    "error": f"Node returned HTTP {resp.status_code}: {resp.text[:200]}"
                }

        except requests.exceptions.Timeout:
            return {"success": False, "error": "Model inference timed out (>120s)"}
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": "Cannot reach sovereign node. It may be offline."}
        except Exception as e:
            return {"success": False, "error": f"Proxy error: {str(e)}"}

    @staticmethod
    def provision_node(client_id: str, node_url: str = None, model_name: str = "llama3:8b", storage_gb: int = 20, hosting_type: str = "Managed") -> dict:
        """
        Provision a new sovereign node for a client.
        Inserts a record into the sovereign_nodes table.
        If hosting_type='Managed', it attempts to spin up a pod on RunPod.
        """
        api_key = SovereignNodeManager.generate_api_key()
        pod_id = None
        status = 'provisioning'
        
        if hosting_type == 'Managed':
            # Automatic RunPod Provisioning
            from services.model_config import get_model_specs
            specs = get_model_specs(model_name)
            
            # Use persistent volume if configured in environment
            storage_id = os.getenv("RUNPOD_VOLUME_ID")
            dc_id = os.getenv("RUNPOD_DATA_CENTER_ID", "US-NJ-1")
            
            rp_res = runpod.create_vllm_pod(
                client_id=client_id, 
                model_name=model_name,
                gpu_type=specs['gpu_type'],
                gpu_count=specs['gpu_count'],
                storage_id=storage_id,
                data_center_id=dc_id
            )
            if "error" in rp_res:
                return {"success": False, "error": f"RunPod Error: {rp_res['error']}"}
            pod_id = rp_res["pod_id"]
            storage_gb = specs['storage_gb'] # Override with recommended storage
            node_url = "https://provisioning..." # Will be updated by background sync
        elif not node_url:
            return {"success": False, "error": "node_url is required for Self-Hosted nodes"}

        try:
            key_hash = SovereignNodeManager._hash_api_key(api_key)
            res = safe_execute(
                supabase_admin.table('sovereign_nodes').insert({
                    'client_id': client_id,
                    'node_url': node_url,
                    'api_key_hash': key_hash,
                    'api_key': f'migrated_{key_hash[:12]}', # Placeholder for legacy schema
                    'model_name': model_name,
                    'status': status,
                    'storage_gb': storage_gb,
                    'pod_id': pod_id,
                    'hosting_type': hosting_type
                })
            )
            if res.data:
                return {"success": True, "node": res.data[0], "api_key": api_key, "pod_id": pod_id}
            return {"success": False, "error": "Insert returned no data"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def regenerate_api_key(client_id: str) -> dict:
        """Regenerate the API key for a client's sovereign node."""
        new_key = SovereignNodeManager.generate_api_key()
        key_hash = SovereignNodeManager._hash_api_key(new_key)
        try:
            res = safe_execute(
                supabase_admin.table('sovereign_nodes')
                .update({
                    'api_key_hash': key_hash,
                    'api_key': f'migrated_{key_hash[:12]}'
                })
                .eq('client_id', client_id)
            )
            if res.data:
                return {"success": True, "api_key": new_key}
            return {"success": False, "error": "Node not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def sync_node_status(client_id: str) -> dict:
        """
        Check the actual status of a RunPod-managed node and update
        the database with the public URL and refined status.
        """
        node = SovereignNodeManager.get_client_node(client_id)
        if not node or not node.get('pod_id'):
            return {"success": False, "error": "Node not managed by cloud (no pod_id)"}

        pod_res = runpod.get_pod_details(node['pod_id'])
        if "error" in pod_res:
            return {"success": False, "error": pod_res["error"]}

        updates = {}
        if pod_res["status"] == "running" and pod_res.get("node_url"):
            updates["node_url"] = pod_res["node_url"]
            updates["status"] = "active"
        elif pod_res["status"] == "provisioning":
            updates["status"] = "provisioning"
        else:
            updates["status"] = "offline"

        if updates:
            try:
                safe_execute(
                    supabase_admin.table('sovereign_nodes')
                    .update(updates)
                    .eq('client_id', client_id)
                )
                return {"success": True, "updates": updates}
            except Exception as e:
                return {"success": False, "error": str(e)}
        
        return {"success": True, "status": "no change"}

    @staticmethod
    def update_node_status(client_id: str, status: str) -> dict:
        """Update the status of a client's sovereign node."""
        valid = ('provisioning', 'active', 'suspended', 'offline')
        if status not in valid:
            return {"success": False, "error": f"Invalid status. Must be one of: {valid}"}
        try:
            res = safe_execute(
                supabase_admin.table('sovereign_nodes')
                .update({'status': status})
                .eq('client_id', client_id)
            )
            if res.data:
                return {"success": True}
            return {"success": False, "error": "Node not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    @staticmethod
    def update_node_model(client_id: str, new_model: str) -> dict:
        """
        Switch the model on a client's sovereign node.
        For Managed nodes, this involves terminating the old pod and 
        starting a new one with the same volume but the new model.
        """
        import os
        node = SovereignNodeManager.get_client_node(client_id)
        if not node:
            return {"success": False, "error": "No node provisioned"}

        if node['hosting_type'] == 'Managed' and node.get('pod_id'):
            # 1. Terminate old pod
            runpod.terminate_pod(node['pod_id'])
            
            # 2. Provision new pod with same volume but new model
            from services.model_config import get_model_specs
            specs = get_model_specs(new_model)
            
            storage_id = os.getenv("RUNPOD_VOLUME_ID")
            dc_id = os.getenv("RUNPOD_DATA_CENTER_ID", "US-NJ-1")
            
            rp_res = runpod.create_vllm_pod(
                client_id=client_id, 
                model_name=new_model,
                gpu_type=specs['gpu_type'],
                gpu_count=specs['gpu_count'],
                storage_id=storage_id,
                data_center_id=dc_id
            )
            
            if "error" in rp_res:
                return {"success": False, "error": f"RunPod Redeploy Error: {rp_res['error']}"}
            
            # 3. Update DB with new pod_id and model_name
            try:
                safe_execute(
                    supabase_admin.table('sovereign_nodes')
                    .update({
                        'pod_id': rp_res["pod_id"],
                        'model_name': new_model,
                        'status': 'provisioning',
                        'node_url': 'https://provisioning...' # Reset until sync
                    })
                    .eq('client_id', client_id)
                )
                return {"success": True, "message": f"Node redeploying with model {new_model}."}
            except Exception as e:
                return {"success": False, "error": str(e)}
        else:
            # For self-hosted, just update the metadata
            try:
                safe_execute(
                    supabase_admin.table('sovereign_nodes')
                    .update({'model_name': new_model})
                    .eq('client_id', client_id)
                )
                return {"success": True, "message": f"Model metadata updated to {new_model}."}
            except Exception as e:
                return {"success": False, "error": str(e)}
