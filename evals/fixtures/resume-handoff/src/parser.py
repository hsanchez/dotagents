def parse_header(value: str) -> tuple[str, str]:
    return tuple(value.split(" ", 1))
