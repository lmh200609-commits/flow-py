import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional, List

from .pool_manager import AccountPoolManager
from .flow_engine import FlowEngine, OUTPUT_DIR

log = logging.getLogger("pool_engine")

class PoolEngine:
    _instance: Optional["PoolEngine"] = None

    def __init__(self):
        self.manager = AccountPoolManager.get_instance()
        # Active engine instances keyed by account_id
        self._engines: Dict[str, FlowEngine] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "PoolEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def get_engine_for_account(self, account: Dict[str, Any]) -> FlowEngine:
        acc_id = account["id"]
        if acc_id not in self._engines:
            engine = FlowEngine(
                profile_dir=Path(account["profile_dir"]),
                project_url=account.get("project_url", "https://flow.google.com/")
            )
            await engine.start()
            self._engines[acc_id] = engine
        return self._engines[acc_id]

    async def generate_with_failover(
        self,
        prompt: str,
        model: str = "Veo 3.1 - Fast",
        aspect_ratio: str = "16:9",
        timeout_s: int = 150
    ) -> Dict[str, Any]:
        """Generate video with automatic failover and account pool rotation."""
        max_attempts = len(self.manager.list_accounts()) or 1
        attempt = 0

        while attempt < max_attempts:
            attempt += 1
            account = self.manager.get_next_available_account()
            if not account:
                log.error("All accounts in pool are exhausted or unavailable!")
                raise RuntimeError("All Google Pro accounts in the pool have exhausted their quota. Please add more accounts or wait for daily reset.")

            acc_id = account["id"]
            log.info("Dispatching task to account [%s: %s] (Attempt %d/%d)", acc_id, account.get("name"), attempt, max_attempts)

            try:
                engine = await self.get_engine_for_account(account)
                result = await engine.generate(
                    prompt=prompt,
                    model=model,
                    aspect_ratio=aspect_ratio,
                    timeout_s=timeout_s
                )

                # Check if generation failed due to quota/credits
                # E.g. prompt result empty, or error keywords
                if result.get("status") == "completed":
                    self.manager.mark_success(acc_id, credits_deducted=10)
                    result["used_account"] = acc_id
                    result["used_account_name"] = account.get("name")
                    return result
                else:
                    # If not completed, could be quota or transient error
                    log.warning("Generation with account %s did not complete. Checking failover...", acc_id)
                    # For safety, mark as exhausted if status is failed repeatedly
                    self.manager.mark_exhausted(acc_id, reason="generation_failed_or_quota")
                    # Continue loop to try next account!

            except Exception as e:
                err_msg = str(e).lower()
                is_net_err = any(kw in err_msg for kw in ["err_connection", "name_not_resolved", "proxy", "socket"]) or ("timed_out" in err_msg and "locator" not in err_msg and "selector" not in err_msg)
                if is_net_err:
                    log.error("Network connection error reaching Google Flow: %s. NOT exhausting account.", e)
                    # Close engine instance to reset connection
                    if acc_id in self._engines:
                        try:
                            await self._engines[acc_id].stop()
                        except Exception:
                            pass
                        del self._engines[acc_id]
                    raise RuntimeError("本地网络无法连接 Google 服务 (ERR_CONNECTION_TIMED_OUT)，请检查梯子/科学上网代理是否开启！")
                
                log.exception("Account %s encountered error: %s. Rotating to next account...", acc_id, e)
                self.manager.mark_exhausted(acc_id, reason=str(e))
                # Rotate to next account

        raise RuntimeError("Failed to generate video after rotating through all available pool accounts.")

    async def stop_all(self):
        for acc_id, engine in self._engines.items():
            try:
                await engine.stop()
            except Exception:
                pass
        self._engines.clear()
        log.info("Stopped all pool engine instances.")

