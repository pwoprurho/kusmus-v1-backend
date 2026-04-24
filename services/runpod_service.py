# services/runpod_service.py
"""
RunPod Service — Automates GPU pod provisioning for Sovereign AI Nodes.
Handles API interactions with RunPod to spin up vLLM containers.
"""

import os
import requests
import json
import time

class RunPodService:
    def __init__(self):
        self.api_key = os.getenv("RUNPOD_API_KEY")
        self.base_url = "https://api.runpod.io/graphql"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

    def _execute_query(self, query: str, variables: dict = None) -> dict:
        """Executes a GraphQL query/mutation against RunPod API."""
        if not self.api_key:
            return {"error": "RUNPOD_API_KEY not configured in environment"}
            
        payload = {"query": query}
        if variables:
            payload["variables"] = variables
            
        try:
            resp = requests.post(self.base_url, headers=self.headers, json=payload, timeout=30)
            if resp.status_code == 200:
                result = resp.json()
                if "errors" in result:
                    return {"error": result["errors"][0]["message"]}
                return result.get("data", {})
            return {"error": f"HTTP {resp.status_code}: {resp.text}"}
        except Exception as e:
            return {"error": str(e)}

    def create_network_volume(self, name: str, size_gb: int = 100, data_center_id: str = "US-NJ-1") -> dict:
        """
        Create a network volume via REST API.
        Returns the volume ID (storageId).
        """
        url = "https://api.runpod.io/v1/network-volumes"
        params = {"api_key": self.api_key}
        payload = {
            "name": name,
            "size_gb": size_gb,
            "data_center_id": data_center_id
        }
        try:
            resp = requests.post(url, params=params, json=payload, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"REST API error {resp.status_code}: {resp.text}"}
        except Exception as e:
            return {"error": str(e)}

    def create_vllm_pod(self, client_id: str, model_name: str, gpu_type: str = "NVIDIA GeForce RTX 4090", gpu_count: int = 1, storage_id: str = None, data_center_id: str = "US-NJ-1") -> dict:
        """
        Provision a new vLLM pod on RunPod.
        If storage_id is provided, the pod will mount the network volume.
        Uses parameterized GraphQL variables to prevent injection.
        """
        # Build input dict safely — no string interpolation in the query
        pod_input = {
            "cloudType": "ALL",
            "gpuCount": gpu_count,
            "volumeInGb": 50,
            "containerDiskInGb": 20,
            "minVcpuCount": 4,
            "minMemoryInGb": 16,
            "gpuTypeId": gpu_type,
            "imageName": "vllm/vllm-openai",
            "dockerArgs": f"--model {model_name}",
            "ports": "8000/http",
            "env": [
                {"key": "CLIENT_ID", "value": client_id}
            ]
        }
        if storage_id:
            pod_input["storageId"] = storage_id
            pod_input["dataCenterId"] = data_center_id

        mutation = """
        mutation CreatePod($input: PodFindAndDeployOnDemandInput!) {
          podFindAndDeployOnDemand(input: $input) {
            id
            imageName
            machineId
          }
        }
        """

        result = self._execute_query(mutation, {"input": pod_input})
        if "error" in result:
            return result
            
        pod_info = result.get("podFindAndDeployOnDemand")
        if not pod_info:
            return {"error": "Deployment failed: No pod info returned"}
        return {"success": True, "pod_id": pod_info["id"]}

    def get_pod_details(self, pod_id: str) -> dict:
        """Fetch real-time details (IP, status) for a specific pod."""
        query = """
        query GetPod($podId: String!) {
          pod(input: { podId: $podId }) {
            id
            runtime {
              uptimeInSeconds
              ports {
                ip
                isPublic
                privatePort
                publicPort
              }
            }
          }
        }
        """

        result = self._execute_query(query, {"podId": pod_id})
        if "error" in result:
            return result
            
        pod = result.get("pod")
        if not pod or not pod.get("runtime"):
            return {"status": "provisioning"}
            
        ports = pod["runtime"].get("ports", [])
        public_ip = None
        public_port = None
        
        for p in ports:
            if p["privatePort"] == 8000:
                public_ip = p["ip"]
                public_port = p["publicPort"]
                break
                
        if public_ip and public_port:
            return {
                "status": "running",
                "node_url": f"http://{public_ip}:{public_port}",
                "uptime": pod["runtime"]["uptimeInSeconds"]
            }
            
        return {"status": "provisioning"}

    def terminate_pod(self, pod_id: str) -> dict:
        """Terminate a running pod to stop billing."""
        mutation = """
        mutation TerminatePod($podId: String!) {
          podTerminate(input: { podId: $podId })
        }
        """
        
        result = self._execute_query(mutation, {"podId": pod_id})
        if "error" in result:
            return result
        return {"success": True}
