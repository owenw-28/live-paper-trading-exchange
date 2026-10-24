from apps.marketdata.topics import HOUR_MS, Topic

ORDER_COMMANDS = Topic("orders.commands", partitions=6, retention_ms=7 * 24 * HOUR_MS)
ALL_TRADING_TOPICS = [ORDER_COMMANDS]
