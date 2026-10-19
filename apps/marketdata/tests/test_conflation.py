from apps.marketdata.conflation import ClientQueue

BTC, ETH = "kraken:BTC/USD", "kraken:ETH/USD"


def test_slow_client_receives_only_the_newest_book():
    queue = ClientQueue(min_book_interval_s=0.1)

    replaced = [queue.put_book(BTC, f"book {n}", ingested_at_ns=n) for n in range(1000)]
    frames, _ = queue.drain(now=0.0)

    assert replaced.count(True) == 999
    assert [f.text for f in frames] == ["book 999"]


def test_books_are_rate_limited_per_instrument():
    queue = ClientQueue(min_book_interval_s=0.1)
    queue.put_book(BTC, "first", 1)
    assert [f.text for f in queue.drain(now=10.0)[0]] == ["first"]

    queue.put_book(BTC, "too soon", 2)
    queue.put_book(ETH, "eth first", 3)
    frames, wait = queue.drain(now=10.04)

    assert [f.text for f in frames] == ["eth first"]
    assert abs(wait - 0.06) < 1e-9
    assert [f.text for f in queue.drain(now=10.1)[0]] == ["too soon"]


def test_trades_are_kept_in_order_and_bounded():
    queue = ClientQueue(min_book_interval_s=0.1, max_trades=200)

    dropped = [queue.put_trade(f"trade {n}", n) for n in range(250)]
    frames, wait = queue.drain(now=0.0)

    assert dropped.count(True) == 50
    assert [f.text for f in frames] == [f"trade {n}" for n in range(50, 250)]
    assert wait is None


def test_nothing_waiting_means_no_wakeup_needed():
    assert ClientQueue(min_book_interval_s=0.1).drain(now=0.0) == ([], None)
