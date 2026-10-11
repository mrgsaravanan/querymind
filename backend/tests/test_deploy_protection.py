import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.rate_limit import RateLimiter, RateLimitExceeded, client_ip


@pytest.fixture()
def make(tmp_path, business_db_path):
    def _make(**kw):
        st = Settings(business_db_path=business_db_path, admin_db_path=tmp_path / "a.db", chroma_path=tmp_path / "c",
                      embedding_backend="hashing", **kw)
        return TestClient(create_app(st, llm_factory=None))
    return _make


# ---------------- admin token ----------------
ADMIN_ROUTES = [("GET", "/admin/schema"), ("GET", "/admin/examples"), ("GET", "/admin/logs"), ("GET", "/admin/logs/export"),
                ("GET", "/admin/guardrails"), ("GET", "/admin/config"), ("GET", "/admin/tables/imported"),
                ("PUT", "/admin/config"), ("PUT", "/admin/guardrails"), ("POST", "/admin/examples"),
                ("POST", "/admin/tables/preview"), ("DELETE", "/admin/tables/orders"), ("DELETE", "/admin/examples/1")]


def test_admin_open_when_no_token_configured(make):
    assert make().get("/admin/config").status_code == 200


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
def test_every_admin_route_requires_the_token(make, method, path):
    c = make(admin_token="s3cret-token")
    assert c.request(method, path).status_code == 401
    assert c.request(method, path, headers={"X-Admin-Token": "wrong"}).status_code == 401
    assert c.request(method, path, headers={"X-Admin-Token": "s3cret-token "}).status_code == 401       # no fuzzy match
    assert c.request(method, path, headers={"X-Admin-Token": ("é" * 40).encode("latin-1")}).status_code == 401              # non-ascii does not crash


def test_correct_token_unlocks_admin_and_public_routes_stay_public(make):
    c = make(admin_token="s3cret-token")
    h = {"X-Admin-Token": "s3cret-token"}
    assert c.get("/admin/schema", headers=h).status_code == 200
    assert c.put("/admin/guardrails", headers=h, json={"max_rows": 50}).json()["max_rows"] == 50
    assert c.get("/health").status_code == 200                                                          # liveness stays open
    assert c.post("/query", json={"question": "Delete all orders"}).json()["status"] == "unsupported"   # public endpoint
    body = c.get("/admin/config").json()
    assert body["error"] == "Admin token required or incorrect." and "s3cret" not in json.dumps(body)


def test_cors_preflight_for_admin_needs_no_token_and_allows_the_header(make):
    c = make(admin_token="t", cors_origins=("https://app.example.com",))
    r = c.options("/admin/config", headers={"Origin": "https://app.example.com", "Access-Control-Request-Method": "GET",
                                            "Access-Control-Request-Headers": "x-admin-token"})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "https://app.example.com"
    assert "x-admin-token" in r.headers["access-control-allow-headers"].lower()


def test_cors_only_allows_configured_origins(make):
    c = make(cors_origins=("https://app.example.com",), cors_origin_regex=r"https://querymind-[a-z0-9-]+\.vercel\.app")
    def allowed(origin):
        r = c.options("/query", headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
        return r.headers.get("access-control-allow-origin")
    assert allowed("https://app.example.com") == "https://app.example.com"
    assert allowed("https://querymind-git-main-me.vercel.app") == "https://querymind-git-main-me.vercel.app"
    assert allowed("https://evil.example.org") is None and allowed("https://querymind.vercel.app.evil.org") is None


# ---------------- rate limiter ----------------
class Clock:
    t = 1_000_000.0

    def __call__(self):
        return self.t


def test_per_client_hourly_limit_slides_and_isolates_clients():
    clk = Clock()
    rl = RateLimiter(per_hour=3, clock=clk)
    for _ in range(3):
        rl.check("a")
    with pytest.raises(RateLimitExceeded) as e:
        rl.check("a")
    assert 0 < e.value.retry_after <= 3601      # rounded up to whole seconds
    rl.check("b")                                   # other clients unaffected
    clk.t += 3601
    rl.check("a")                                   # window slid


def test_rejected_requests_are_not_counted_and_cap_is_global():
    clk = Clock()
    rl = RateLimiter(per_hour=2, daily_cap=3, clock=clk)
    rl.check("a"); rl.check("a")
    for _ in range(10):
        with pytest.raises(RateLimitExceeded):
            rl.check("a")                           # hammering must not push the daily counter up
    rl.check("b")                                   # 3rd accepted request overall
    with pytest.raises(RateLimitExceeded, match="daily"):
        rl.check("c")
    clk.t += 86401
    rl.check("c")                                   # new day


def test_disabled_limiter_never_blocks():
    rl = RateLimiter()
    assert not rl.enabled
    for _ in range(1000):
        rl.check("a")


@pytest.mark.parametrize("xff,peer,hops,expected", [
    ("9.9.9.9", "10.0.0.1", 1, "9.9.9.9"),
    ("1.1.1.1, 9.9.9.9", "10.0.0.1", 1, "9.9.9.9"),            # leftmost is client-supplied: ignored
    ("6.6.6.6, 1.1.1.1, 9.9.9.9", "10.0.0.1", 2, "1.1.1.1"),
    (None, "10.0.0.1", 1, "10.0.0.1"), ("9.9.9.9", "10.0.0.1", 0, "10.0.0.1"), ("9.9.9.9", None, 0, "unknown"),
    ("9.9.9.9", "10.0.0.1", 3, "10.0.0.1"),                     # fewer entries than trusted hops: fall back to peer
])
def test_client_ip(xff, peer, hops, expected):
    assert client_ip(xff, peer, hops) == expected


def test_query_endpoint_returns_429_with_retry_after_and_cannot_be_spoofed(make):
    c = make(rate_limit_per_hour=2, rate_limit_proxy_hops=1)
    q = {"question": "Delete all orders"}
    h = lambda left: {"X-Forwarded-For": f"{left}, 9.9.9.9"}  # noqa: E731  same real client, varying spoofed prefix
    assert c.post("/query", json=q, headers=h("1.1.1.1")).status_code == 200
    assert c.post("/query", json=q, headers=h("2.2.2.2")).status_code == 200
    r = c.post("/query", json=q, headers=h("3.3.3.3"))
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0 and "Too many" in r.json()["error"]
    other = c.post("/query", json=q, headers={"X-Forwarded-For": "1.1.1.1, 8.8.8.8"})      # a genuinely different client
    assert other.status_code == 200
    assert c.get("/health").status_code == 200 and c.get("/admin/config").status_code == 200  # other routes not limited


def test_daily_cap_applies_across_clients(make):
    c = make(daily_query_cap=2, rate_limit_proxy_hops=1)
    q = {"question": "Delete all orders"}
    codes = [c.post("/query", json=q, headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code for i in range(4)]
    assert codes == [200, 200, 429, 429]


def test_no_limits_by_default(make):
    c = make()
    assert all(c.post("/query", json={"question": "Delete all orders"}).status_code == 200 for _ in range(15))
