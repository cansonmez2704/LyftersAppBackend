"""
Locust load test for GymHub.

Pre-req: `python manage.py seed_loadtest` has run and produced fixtures.json.

Each simulated user logs in once on start, then performs a weighted mix of the
endpoints a real user hits during a normal session. Token refresh on 401 is
handled in-band so a single expired token doesn't tank the run.

Run:
    cd GymHubBackend/loadtest
    locust -f locustfile.py --host http://127.0.0.1:8000

Then open http://127.0.0.1:8089 to drive ramp/hold from the web UI, or
add `--users 200 --spawn-rate 1 --run-time 15m --headless`.
"""
import json
import random
from pathlib import Path

from locust import HttpUser, between, events, task
from locust.exception import StopUser

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures.json"

# Loaded once on worker startup.
_fixture = json.loads(FIXTURE_PATH.read_text())
USERS = _fixture["users"]
PASSWORD = _fixture["password"]
POST_UUIDS = _fixture["post_uuids"]
PROFILE_UUIDS = [u["uuid"] for u in USERS]

# Round-robin so each simulated user grabs a distinct seeded account.
_user_iter = iter(USERS)


def _next_credentials():
    global _user_iter
    try:
        return next(_user_iter)
    except StopIteration:
        # Wrap around — fine for repeated logins beyond fixture size.
        _user_iter = iter(USERS)
        return next(_user_iter)


class GymHubUser(HttpUser):
    # Simulates ~1 action every 1-3s — closer to a scrolling user than a bot.
    wait_time = between(1, 3)

    def on_start(self):
        creds = _next_credentials()
        self.username = creds["username"]
        self.my_uuid = creds["uuid"]
        self.access = None
        self.refresh = None
        # Cache feed-page post UUIDs so subsequent tasks can act on real IDs.
        self.recent_post_uuids = []
        self._login()

    # -------- auth ----------

    def _login(self):
        with self.client.post(
            "/api/v1/auth/login/",
            json={"username": self.username, "password": PASSWORD},
            name="POST /auth/login",
            catch_response=True,
        ) as r:
            if r.status_code != 200:
                msg = (
                    f"login failed for {self.username}: HTTP {r.status_code} body={r.text[:200]}\n"
                    f"  -> server is probably hitting the wrong DB. Make sure gunicorn was started "
                    f"with DJANGO_DB_NAME=gymhub_loadtest (use ./loadtest/run_loadtest.sh)."
                )
                r.failure(msg)
                print(f"[locust] FATAL: {msg}")
                raise StopUser()
            data = r.json()
            self.access = data.get("access")
            self.refresh = data.get("refresh")

    def _refresh_token(self):
        if not self.refresh:
            return False
        with self.client.post(
            "/api/v1/users/token/refresh/",
            json={"refresh": self.refresh},
            name="POST /token/refresh",
            catch_response=True,
        ) as r:
            if r.status_code == 200:
                self.access = r.json().get("access", self.access)
                return True
            r.failure(f"refresh failed: {r.status_code}")
        return False

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self.access}"} if self.access else {}

    def _request(self, method, path, name=None, json_body=None, params=None):
        """Wraps client.request with single-shot 401 -> refresh -> retry."""
        kwargs = {"headers": self._auth_headers(), "name": name or path, "catch_response": True}
        if json_body is not None:
            kwargs["json"] = json_body
        if params is not None:
            kwargs["params"] = params
        with self.client.request(method, path, **kwargs) as r:
            if r.status_code == 401 and self._refresh_token():
                # Retry once with fresh token.
                kwargs["headers"] = self._auth_headers()
                with self.client.request(method, path, **kwargs) as r2:
                    self._mark(r2)
                    return r2
            self._mark(r)
            return r

    @staticmethod
    def _mark(r):
        # Treat 2xx as success, 429 as expected throttle (not a failure),
        # everything else as a real failure so percentile reports are honest.
        if r.status_code < 400 or r.status_code == 429:
            r.success()
        else:
            r.failure(f"{r.status_code} {r.text[:120]}")

    # -------- read-heavy tasks (the bulk of real traffic) ----------

    @task(30)
    def browse_feed(self):
        r = self._request("GET", "/api/v1/community/feed/", name="GET /feed")
        if r.status_code == 200:
            try:
                results = r.json().get("results", [])
                uuids = [p.get("uuid") for p in results if p.get("uuid")]
                if uuids:
                    self.recent_post_uuids = uuids
            except ValueError:
                pass

    @task(10)
    def view_post_detail(self):
        uuid = self._pick_post_uuid()
        if uuid:
            self._request("GET", f"/api/v1/community/posts/{uuid}/", name="GET /posts/[uuid]")

    @task(8)
    def view_comments(self):
        uuid = self._pick_post_uuid()
        if uuid:
            self._request(
                "GET",
                f"/api/v1/community/posts/{uuid}/comments/",
                name="GET /posts/[uuid]/comments",
            )

    @task(5)
    def view_profile(self):
        target = random.choice(PROFILE_UUIDS)
        self._request("GET", f"/api/v1/users/profiles/{target}/", name="GET /profiles/[uuid]")

    @task(3)
    def search(self):
        term = random.choice(["loadtest", "post", "user", "workout", "bicep"])
        self._request("GET", "/api/v1/search/", name="GET /search", params={"q": term, "type": "all"})

    @task(2)
    def list_workouts(self):
        self._request("GET", "/api/v1/workouts/", name="GET /workouts")

    # -------- write-ish tasks (lower weight, like real usage) ----------

    @task(8)
    def react_to_post(self):
        uuid = self._pick_post_uuid()
        if uuid:
            self._request(
                "POST",
                f"/api/v1/community/posts/{uuid}/react/",
                name="POST /posts/[uuid]/react",
                json_body={"reaction_type": random.choice(["like", "dislike"])},
            )

    @task(2)
    def add_comment(self):
        uuid = self._pick_post_uuid()
        if uuid:
            self._request(
                "POST",
                f"/api/v1/community/posts/{uuid}/comments/",
                name="POST /posts/[uuid]/comments",
                json_body={"body": f"loadtest comment {random.randint(0, 10**6)}", "parent": None},
            )

    @task(1)
    def create_post(self):
        self._request(
            "POST",
            "/api/v1/community/posts/",
            name="POST /posts",
            json_body={
                "title": f"lt {random.randint(0, 10**9)}",
                "description": "load test post body",
                "post_type": "general",
                "visibility": "public",
            },
        )

    @task(1)
    def toggle_follow(self):
        target = random.choice(PROFILE_UUIDS)
        if target == self.my_uuid:
            return
        self._request(
            "POST",
            f"/api/v1/users/profiles/{target}/follow/",
            name="POST /profiles/[uuid]/follow",
        )

    # -------- helpers ----------

    def _pick_post_uuid(self):
        if self.recent_post_uuids:
            return random.choice(self.recent_post_uuids)
        return random.choice(POST_UUIDS) if POST_UUIDS else None


@events.test_start.add_listener
def _on_start(environment, **kwargs):
    print(f"[locust] fixture loaded: {len(USERS)} users, {len(POST_UUIDS)} posts")
