from client import ApiClient


def refresh(client: ApiClient, new_token: str) -> None:
    client.refresh_token(new_token)
