class ApiClient:
    def __init__(self, token: str) -> None:
        self.token = token
        self.headers = {"Authorization": f"Bearer {token}"}

    def refresh_token(self, token: str) -> None:
        self.token = token

    def checkout(self) -> dict[str, str]:
        return self.headers
