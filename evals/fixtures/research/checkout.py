from client import ApiClient


def send_checkout(client: ApiClient) -> dict[str, str]:
    return client.checkout()
