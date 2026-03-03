"""
Load tests for Link Shortener API using Locust.

Run:
    locust -f tests/locustfile.py --host http://localhost:8000
"""

import random
import string

from locust import HttpUser, task, between


class LinkShortenerUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        uid = "".join(random.choices(string.ascii_lowercase, k=8))
        self.username = f"load_{uid}"
        self.client.post(
            "/auth/register",
            json={"username": self.username, "password": "loadtest"},
        )
        resp = self.client.post(
            "/auth/login",
            data={"username": self.username, "password": "loadtest"},
        )
        if resp.status_code == 200:
            self.token = resp.json()["access_token"]
            self.headers = {"Authorization": f"Bearer {self.token}"}
        else:
            self.headers = {}
        self.short_codes: list[str] = []

    @task(3)
    def create_link(self):
        resp = self.client.post(
            "/links/shorten",
            json={"original_url": "https://example.com"},
            headers=self.headers,
        )
        if resp.status_code == 201:
            self.short_codes.append(resp.json()["short_code"])

    @task(5)
    def redirect_link(self):
        if self.short_codes:
            code = random.choice(self.short_codes)
            self.client.get(
                f"/links/{code}",
                name="/links/{short_code}",
                allow_redirects=False,
            )

    @task(2)
    def get_stats(self):
        if self.short_codes:
            code = random.choice(self.short_codes)
            self.client.get(
                f"/links/{code}/stats",
                name="/links/{short_code}/stats",
                headers=self.headers,
            )

    @task(1)
    def search_link(self):
        self.client.get(
            "/links/search",
            params={"original_url": "https://example.com/"},
        )
