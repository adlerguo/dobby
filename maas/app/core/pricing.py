MODEL_PRICES_PER_MILLION: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1": (2.00, 8.00),
    "deepseek-chat": (0.27, 1.10),
    "qwen-max": (1.60, 6.40),
    "claude-sonnet-4": (3.00, 15.00),
}


def estimate_cost(model: str | None, input_tokens: int | str | None, output_tokens: int | str | None) -> float:
    if not model:
        return 0.0

    normalized = model.lower()
    prices = sorted(MODEL_PRICES_PER_MILLION.items(), key=lambda item: len(item[0]), reverse=True)
    for prefix, (input_price, output_price) in prices:
        if normalized.startswith(prefix):
            return _cost(input_price, output_price, input_tokens, output_tokens)
    return 0.0


def estimate_custom_cost(
    input_price_per_million: float | int | str | None,
    output_price_per_million: float | int | str | None,
    input_tokens: int | str | None,
    output_tokens: int | str | None,
) -> float | None:
    input_price = _to_float(input_price_per_million)
    output_price = _to_float(output_price_per_million)
    if input_price is None or output_price is None:
        return None
    return _cost(input_price, output_price, input_tokens, output_tokens)


def _cost(input_price: float, output_price: float, input_tokens: int | str | None, output_tokens: int | str | None) -> float:
    input_total = _token_count(input_tokens) * input_price
    output_total = _token_count(output_tokens) * output_price
    return round((input_total + output_total) / 1_000_000, 6)


def _token_count(value: int | str | None) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _to_float(value: float | int | str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
