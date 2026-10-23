"""Record raw messages from Kraken websocket and feed to a JSON Lines file.

Usage: uv run python scripts/record_kraken.py [seconds]
"""

import asyncio
import json
import sys
import time
from pathlib import Path

from websockets.asyncio.client import connect

URL = "wss://ws.kraken.com/v2"
SYMBOLS = ["BTC/USD", "ETH/USD"]


async def record(seconds: float, output: Path) -> int:
    count = 0
    async with connect(URL) as ws:
        await ws.send(
            json.dumps(
                {
                    "method": "subscribe",
                    "params": {"channel": "book", "symbol": SYMBOLS, "depth": 10},
                }
            )
        )
        await ws.send(
            json.dumps({"method": "subscribe", "params": {"channel": "trade", "symbol": SYMBOLS}})
        )

        deadline = time.monotonic() + seconds
        with output.open("w") as f:
            while (remaining := deadline - time.monotonic()) > 0:
                try:
                    raw = await asyncio.wait_for(ws.recv(decode=True), timeout=remaining)
                except TimeoutError:
                    break
                f.write(raw + "\n")
                count += 1
    return count


def main() -> None:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 30
    output = Path("recordings") / f"kraken-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    output.parent.mkdir(exist_ok=True)
    count = asyncio.run(record(seconds, output))
    print(f"Recorded {count} messages to {output}")


if __name__ == "__main__":
    main()
