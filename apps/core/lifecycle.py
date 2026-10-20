"""Process lifecycle helpers shared by the long-running commands."""

import asyncio
import contextlib
import signal
from collections.abc import Coroutine


async def run_until_stopped(main: Coroutine) -> None:
    """Run `main` until SIGINT or SIGTERM arrives, then cancel it so its cleanup runs."""
    task = asyncio.ensure_future(main)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, task.cancel)
    with contextlib.suppress(asyncio.CancelledError):
        await task
