import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import run_sim

if __name__ == "__main__":
    asyncio.run(run_sim.run_simulation())
