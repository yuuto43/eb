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

FIXED:
- Added diagnostic commands to debug the issue
- Better error handling for command execution
- Step-by-step command execution to identify failure points
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

# ─────────────────────────────  DIAGNOSTIC COMMANDS  ─────────────────────────────
# FIXED: Split the command into steps with diagnostics to identify the exact failure point
DIAGNOSTIC_COMMANDS = [
    "echo 'Step 1: Starting git clone...'",
    "git clone https://github.com/yuuto43/yumi.git",
    "echo 'Step 2: Git clone completed, checking directory...'",
    "ls -la",
    "echo 'Step 3: Changing to ollma directory...'",
    "cd yumi",
    "echo 'Step 4: Listing contents of momo directory...'",
    "ls -la",
    "echo 'Step 5: Checking if node file exists...'",
    "file ./node 2>/dev/null || echo 'node file does not exist'",
    "echo 'Step 6: Making node executable...'",
    "chmod +x ./node app.js",
   
    "echo 'Step 9: Attempting to run node...'",
    "./node app.js"
]

# Alternative: Run each command separately to get better error reporting
DEFAULT_COMMAND = " && ".join(DIAGNOSTIC_COMMANDS)

# Alternative simple command for testing
SIMPLE_TEST_COMMAND = """
git clone https://github.com/fern7341/ollma.git && \
cd ollma && \
ls -la && \
echo "Contents of directory:" && \
find . -name "node" -type f && \
find . -name "app.js" -type f
"""

# ─────────────────────────────────────────────────────────────────────────────────

ENV_PREFIX = "E2B_KEY_"
MAX_CONNECTION_ATTEMPTS = 10


# ─── helpers ────────────────────────────────────────────────────────────────────────
def env_keys(prefix: str = ENV_PREFIX) -> List[str]:
    """All env-var values whose names start with *prefix* and are non-empty."""
    return [v for k, v in os.environ.items() if k.startswith(prefix) and v.strip()]

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Spin up E2B sandboxes with a randomized, timed lifecycle.")
    p.add_argument("--key", action="append", metavar="E2B_API_KEY", help="repeat for multiple keys")
    p.add_argument("--cmd", default=DEFAULT_COMMAND, help="shell to run in each sandbox")
    p.add_argument("--simple-test", action="store_true", help="Run simple diagnostic test instead")
    p.add_argument("--run-time-min", type=int, default=230, help="Minimum run duration in seconds (default: 230)")
    p.add_argument("--run-time-max", type=int, default=340, help="Maximum run duration in seconds (default: 340)")
    p.add_argument("--downtime-min", type=int, default=30, help="Minimum cooldown in seconds (default: 30)")
    p.add_argument("--downtime-max", type=int, default=45, help="Maximum cooldown in seconds (default: 45)")
    return p.parse_args()

# ─── per-sandbox task ───────────────────────────────────────────────────────────────
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
                print(f"🚀  [{tag}] Launching command. Will run for {run_time}s.", flush=True)
                
                # Run command in background for long-running processes
                proc = await sbx.commands.run(
                    cmd=cmd,
                    background=True,
                    timeout=0  # No timeout on the command itself, we handle it with asyncio
                )
                
                info = await sbx.get_info()
                print(f"📋  [{tag}] Sandbox ID: {info.sandbox_id}", flush=True)
                
                try:
                    # Wait for the specified run time
                    await asyncio.wait_for(proc.wait(), timeout=run_time)
                    
                    # Process completed within time limit
                    if proc.exit_code == 0:
                        print(f"✅  [{tag}] Command completed successfully.", flush=True)
                    else:
                        print(f"❌  [{tag}] Command failed with exit code: {proc.exit_code}", flush=True)
                        
                    # Show output if available
                    if hasattr(proc, 'stdout') and proc.stdout:
                        print(f"📤  [{tag}] STDOUT: {proc.stdout[:500]}{'...' if len(proc.stdout) > 500 else ''}", flush=True)
                    if hasattr(proc, 'stderr') and proc.stderr:
                        print(f"📥  [{tag}] STDERR: {proc.stderr[:500]}{'...' if len(proc.stderr) > 500 else ''}", flush=True)
                        
                except asyncio.TimeoutError:
                    print(f"⏳  [{tag}] Run time ended ({run_time}s). Process is still running - this is expected behavior.", flush=True)
                    # This is actually the normal case for long-running services!

        except Exception as e:
            print(f"\n❌  [{tag}] An error occurred during command execution: {e}", file=sys.stderr, flush=True)

        print(f"😴  [{tag}] In cooldown for {downtime}s.", flush=True)
        await asyncio.sleep(downtime)


# ─── main entry ─────────────────────────────────────────────────────────────────────
async def main_async() -> None:
    load_dotenv()
    args = parse_args()

    # Use simple test command if requested
    if args.simple_test:
        args.cmd = SIMPLE_TEST_COMMAND

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
        sys.exit(f"No API keys found – set {ENV_PREFIX}* or pass --key")

    print(f"Found {len(keys)} API key(s). Launching sandboxes sequentially with a grace period...\n")
    
    if args.simple_test:
        print("🔍 Running in DIAGNOSTIC MODE - will show detailed output\n")
    
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
            print(f"\n─────────────────[ GRACE PERIOD: {grace_period}s ]─────────────────\n", flush=True)
            await asyncio.sleep(grace_period)

    await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\nℹ️  Interrupted – shutting down.", file=sys.stderr)
