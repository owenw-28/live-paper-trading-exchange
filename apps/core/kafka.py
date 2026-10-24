"""Small helpers shared by every Kafka consumer."""

from confluent_kafka import Message


def text_headers(message: Message) -> dict[str, str]:
    """Message headers as text. Kafka headers may arrive as a dict or a list of pairs."""
    headers = message.headers() or []
    pairs = headers.items() if isinstance(headers, dict) else headers
    return {
        key: value.decode() if isinstance(value, bytes) else value
        for key, value in pairs
        if value is not None
    }
