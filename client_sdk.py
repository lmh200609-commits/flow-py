import time
import requests
from typing import Optional, Dict, Any, List


class FlowVideoClient:
    """Python Client for Google Flow (Veo 3.1) Multi-Account Pool Gateway with AI Director."""

    def __init__(self, base_url: str = "http://127.0.0.1:8765", api_key: str = "sk-flow-84049243d7bd02b5f3c17e9041e073ec"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def check_health(self) -> Dict[str, Any]:
        resp = requests.get(f"{self.base_url}/health", headers=self.headers, timeout=5)
        resp.raise_for_status()
        return resp.json()

    def get_pool_accounts(self) -> Dict[str, Any]:
        """Query all accounts in the pool and their real-time quotas."""
        resp = requests.get(f"{self.base_url}/v1/pool/accounts", headers=self.headers, timeout=5)
        resp.raise_for_status()
        return resp.json()

    def get_credits(self) -> Dict[str, Any]:
        """Get aggregated credits across all active accounts in pool."""
        resp = requests.get(f"{self.base_url}/v1/credits", headers=self.headers, timeout=5)
        resp.raise_for_status()
        return resp.json()

    def list_models(self) -> Dict[str, Any]:
        resp = requests.get(f"{self.base_url}/v1/models", headers=self.headers, timeout=5)
        resp.raise_for_status()
        return resp.json()

    def compile_prompt(
        self,
        subject: str,
        genre: str = "sci-fi",
        shot_type: Optional[str] = None,
        style_anchor: Optional[str] = None
    ) -> Dict[str, Any]:
        """Uses the AI Director Prompt Compiler to produce diffusion-ready prompts."""
        payload = {
            "subject": subject,
            "genre": genre,
            "shot_type": shot_type,
            "style_anchor": style_anchor
        }
        resp = requests.post(f"{self.base_url}/v1/director/compile_prompt", json=payload, headers=self.headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def plan_storyboard(
        self,
        title: str,
        narrative: str,
        genre: str = "sci-fi",
        num_shots: int = 3,
        style_anchor: Optional[str] = None,
        custom_shots: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Generates a structured multi-shot storyboard plan for preview and confirmation."""
        payload = {
            "title": title,
            "narrative": narrative,
            "genre": genre,
            "num_shots": num_shots,
            "style_anchor": style_anchor,
            "custom_shots": custom_shots
        }
        resp = requests.post(f"{self.base_url}/v1/director/plan_storyboard", json=payload, headers=self.headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def create_storyboard(
        self,
        title: str,
        narrative: str,
        genre: str = "sci-fi",
        num_shots: int = 3,
        style_anchor: Optional[str] = None,
        custom_shots: Optional[List[Dict[str, Any]]] = None,
        transition: str = "fast",
        wait: bool = False,
        poll_interval: int = 5,
        timeout: int = 600
    ) -> Dict[str, Any]:
        """Submits an end-to-end multi-shot storyboard for rendering and FFmpeg assembly."""
        payload = {
            "title": title,
            "narrative": narrative,
            "genre": genre,
            "num_shots": num_shots,
            "style_anchor": style_anchor,
            "custom_shots": custom_shots,
            "transition": transition,
            "wait": False
        }
        resp = requests.post(f"{self.base_url}/v1/storyboard/create", json=payload, headers=self.headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        sb_id = data["storyboard_id"]

        if not wait:
            return data

        start = time.time()
        while time.time() - start < timeout:
            time.sleep(poll_interval)
            status_resp = self.get_storyboard_status(sb_id)
            if status_resp.get("status") in ["completed", "failed"]:
                return status_resp

        raise TimeoutError(f"Storyboard execution timed out after {timeout} seconds.")

    def get_storyboard_status(self, storyboard_id: str) -> Dict[str, Any]:
        resp = requests.get(f"{self.base_url}/v1/storyboard/status/{storyboard_id}", headers=self.headers, timeout=10)
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
        """Submit a prompt to generate single video using pool with auto failover."""
        payload = {
            "prompt": prompt,
            "model": model,
            "aspect_ratio": aspect_ratio,
            "wait": False
        }
        resp = requests.post(f"{self.base_url}/v1/video/generations", json=payload, headers=self.headers, timeout=10)
        resp.raise_for_status()
        task = resp.json()
        task_id = task["task_id"]

        if not wait:
            return task

        start = time.time()
        while time.time() - start < timeout:
            time.sleep(poll_interval)
            status_resp = requests.get(f"{self.base_url}/v1/video/status/{task_id}", headers=self.headers, timeout=10)
            status_resp.raise_for_status()
            current = status_resp.json()
            if current["status"] in ["completed", "failed"]:
                return current

        raise TimeoutError(f"Video generation timed out after {timeout} seconds.")


if __name__ == "__main__":
    client = FlowVideoClient()
    print("Health:", client.check_health())
    print("Credits:", client.get_credits())
    compiled = client.compile_prompt("雨夜赛博朋克追逐", genre="cyberpunk")
    print("Compiled Prompt:", compiled["compiled_prompt"])
    plan = client.plan_storyboard("深空漫游", "宇航员出舱太空行走，与星环合影", genre="sci-fi", num_shots=2)
    print("Plan:", plan["title"], "with", len(plan["shots"]), "shots.")
