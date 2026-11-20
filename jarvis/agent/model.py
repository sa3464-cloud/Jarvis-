"""Optional model boundary. No provider is configured or called in this build."""


def status() -> dict:
    return {
        "available": False,
        "label": "Model unavailable — local fallback",
        "reason": "No model provider has been approved and configured.",
    }


def generate(_messages: list[dict]) -> None:
    """Reserved server-side adapter entry point; intentionally unavailable."""
    return None
