import time
import requests
from typing import Optional, Dict, Any, List

class FlowVideoClient:
    """Python Client for Google Flow (Veo 3.1) Multi-Account Pool Gateway."""

    def __init__(self, base_url: str = "http://127.0.0.1:8765"):
        self.base_url = base_url.rstrip("/")

    def check_health(self) -> Dict[str, Any]:
        resp = requests.get(f"{self.base_url}/health", timeout=5)
        resp.raise_for_status()
        return resp.json()

    def get_pool_accounts(self) -> Dict[str, Any]:
        """Query all accounts in the pool and their real-time quotas."""
        resp = requests.get(f"{self.base_url}/v1/pool/accounts", timeout=5)
        resp.raise_for_status()
        return resp.json()

    def get_credits(self) -> Dict[str, Any]:
        """Get aggregated credits across all active accounts in pool."""
        resp = requests.get(f"{self.base_url}/v1/credits", timeout=5)
        resp.raise_for_status()
        return resp.json()

    def list_models(self) -> Dict[str, Any]:
        resp = requests.get(f"{self.base_url}/v1/models", timeout=5)
        resp.raise_for_status()
        return resp.json()

    def generate_video(
        self,
        prompt: str,
        model: str = "Veo 3.1 - Fast",
        aspect_ratio: str = "16:9",
        wait: bool = True,
        poll_interval: int = 4,
        timeout: int = 150
    ) -> Dict[str, Any]:
        """Submit a prompt to generate video using pool with auto failover.

        If wait=True, this function polls until completion and returns the final result.
        """
        payload = {
            "prompt": prompt,
            "model": model,
            "aspect_ratio": aspect_ratio,
            "wait": False
        }
        resp = requests.post(f"{self.base_url}/v1/video/generations", json=payload, timeout=10)
        resp.raise_for_status()
        task = resp.json()
        task_id = task["task_id"]

        if not wait:
            return task

        # Polling
        start = time.time()
        while time.time() - start < timeout:
            time.sleep(poll_interval)
            status_resp = requests.get(f"{self.base_url}/v1/video/status/{task_id}", timeout=10)
            status_resp.raise_for_status()
            current = status_resp.json()
            if current["status"] in ["completed", "failed"]:
                return current

        raise TimeoutError(f"Video generation timed out after {timeout} seconds.")

if __name__ == "__main__":
    client = FlowVideoClient()
    print("Health:", client.check_health())
    print("Credits:", client.get_credits())
    print("Accounts:", client.get_pool_accounts())
