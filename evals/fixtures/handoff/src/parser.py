def parse_header(value: str) -> tuple[str, str]:
    scheme, token = value.split(" ", 1)
    return scheme, token
