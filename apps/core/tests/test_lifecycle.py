import asyncio
import os
import signal

import pytest

from apps.core.lifecycle import run_until_stopped


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_signal_cancels_main_and_runs_its_cleanup(sig):
    events = []

    async def main():
        try:
            events.append("started")
            await asyncio.sleep(60)
        finally:
            events.append("cleaned up")

    async def scenario():
        asyncio.get_running_loop().call_later(0.05, os.kill, os.getpid(), sig)
        await run_until_stopped(main())

    asyncio.run(scenario())

    assert events == ["started", "cleaned up"]
