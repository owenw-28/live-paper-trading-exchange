"""Leader election with a Postgres advisory lock: of several identical processes, one is active.

The lock belongs to a dedicated connection (outside Django's pool). If the leader dies, its
connection drops and Postgres frees the lock, so a standby takes over.
"""

import time
from collections.abc import Callable

import psycopg
from django.conf import settings


def dedicated_connection() -> psycopg.Connection:
    db = settings.DATABASES["default"]
    return psycopg.connect(
        dbname=db["NAME"],
        user=db["USER"],
        password=db["PASSWORD"],
        host=db["HOST"],
        port=db["PORT"],
        autocommit=True,
    )


def wait_to_lead(
    connection: psycopg.Connection,
    lock_id: int,
    stopping: Callable[[], bool],
    on_standby: Callable[[], None] = lambda: None,
    retry_s: float = 2.0,
) -> bool:
    """Block until this process holds the lock (True), or `stopping()` becomes true (False)."""
    while not stopping():
        row = connection.execute("SELECT pg_try_advisory_lock(%s)", (lock_id,)).fetchone()
        if row is not None and row[0]:
            return True
        on_standby()
        time.sleep(retry_s)
    return False
