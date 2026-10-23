"""Load test: many WebSocket clients against the running stack, measuring delivered latency.

Usage: uv run python scripts/ws_load.py --clients 100 --seconds 600

Each client connects like a browser, skips its connection snapshot, and timestamps every live
book it receives. At the end the script also asks Prometheus for the server-side latency
histograms over the same window, so client and server measurements can be compared.
"""

import argparse
import asyncio
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime

from websockets.asyncio.client import connect
from websockets.typing import Origin

SNAPSHOT_GRACE_S = 1.0  # frames in the first second after connecting are the snapshot


@dataclass
class ClientStats:
    frames: int = 0
    book_latencies_ms: list[float] = field(default_factory=list)
    kraken_to_ingest_ms: list[float] = field(default_factory=list)
    error: str | None = None


async def run_client(url: str, origin: str, deadline: float, stats: ClientStats) -> None:
    try:
        async with connect(url, origin=Origin(origin), open_timeout=10) as ws:
            connected_at = time.monotonic()
            while (remaining := deadline - time.monotonic()) > 0:
                try:
                    text = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except TimeoutError:
                    break
                received_ns = time.time_ns()
                frame = json.loads(text)
                stats.frames += 1
                if frame["type"] != "book" or time.monotonic() - connected_at < SNAPSHOT_GRACE_S:
                    continue
                data = frame["data"]
                stats.book_latencies_ms.append((received_ns - data["ingested_at_ns"]) / 1e6)
                exchange_ns = datetime.fromisoformat(data["exchange_ts"]).timestamp() * 1e9
                stats.kraken_to_ingest_ms.append((data["ingested_at_ns"] - exchange_ns) / 1e6)
    except Exception as exc:  # report every failure; one bad client must not stop the test
        stats.error = repr(exc)


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(p / 100 * len(ordered)))]


def server_quantile(prometheus: str, metric: str, quantile: float, window_s: int) -> float | None:
    query = (
        f"histogram_quantile({quantile}, sum by (le) "
        f'(rate({metric}_seconds_bucket{{kind="book"}}[{window_s}s])))'
    )
    url = f"{prometheus}/api/v1/query?" + urllib.parse.urlencode({"query": query})
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            result = json.load(response)["data"]["result"]
    except OSError:
        return None
    return float(result[0]["value"][1]) * 1000 if result else None


async def main(args: argparse.Namespace) -> None:
    deadline = time.monotonic() + args.seconds
    clients = [ClientStats() for _ in range(args.clients)]
    tasks = []
    for stats in clients:
        tasks.append(asyncio.create_task(run_client(args.url, args.origin, deadline, stats)))
        await asyncio.sleep(args.ramp_s / args.clients)  # don't connect everyone at once
    await asyncio.gather(*tasks)

    failed = [c for c in clients if c.error]
    latencies = [ms for c in clients for ms in c.book_latencies_ms]
    upstream = [ms for c in clients for ms in c.kraken_to_ingest_ms]
    print(f"Clients: {len(clients) - len(failed)} succeeded, {len(failed)} failed")
    for c in failed[:5]:
        print(f"  failure: {c.error}")
    if not latencies:
        print("No live books received.")
        return
    per_client = sum(c.frames for c in clients) / len(clients) / args.seconds
    print(f"Frames per client per second: {per_client:.1f}")
    print(f"Live books measured: {len(latencies)}")
    print("\nLatency (ms)                       p50      p99      max")
    print(
        f"  Delivered, ingest -> client  {percentile(latencies, 50):7.1f}  "
        f"{percentile(latencies, 99):7.1f}  {max(latencies):7.1f}   (measured by clients)"
    )
    print(
        f"  Upstream, Kraken -> ingest   {percentile(upstream, 50):7.1f}  "
        f"{percentile(upstream, 99):7.1f}            (depends on clock sync)"
    )
    window = max(60, int(args.seconds))
    for label, metric in [
        ("Pipeline, ingest -> broadcast", "marketdata_ingest_to_broadcast"),
        ("Delivered, ingest -> send   ", "marketdata_ingest_to_send"),
    ]:
        p50 = server_quantile(args.prometheus, metric, 0.5, window)
        p99 = server_quantile(args.prometheus, metric, 0.99, window)
        if p50 is None or p99 is None:
            print(f"  {label}  (no data from Prometheus)")
        else:
            print(f"  {label} {p50:7.1f}  {p99:7.1f}            (server histogram)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--clients", type=int, default=100)
    parser.add_argument("--seconds", type=float, default=600)
    parser.add_argument("--ramp-s", type=float, default=5.0, help="spread connections over this")
    parser.add_argument("--url", default="ws://localhost:8081/ws/market/")
    parser.add_argument("--origin", default="http://localhost:8081")
    parser.add_argument(
        "--prometheus", default="http://localhost:3000/api/datasources/proxy/uid/prometheus"
    )
    asyncio.run(main(parser.parse_args()))
