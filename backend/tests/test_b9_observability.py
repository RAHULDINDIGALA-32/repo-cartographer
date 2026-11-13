from app.api.security import verify_hmac_signature
from app.observability.metrics import Metrics


def test_metrics_render_bounded_labels_and_histogram():
    registry = Metrics()
    registry.inc("http_requests_total", route="/v1/repos/{repo_id}", method="GET")
    registry.observe("http_request_duration_seconds", 0.25, route="/v1/repos/{repo_id}")

    output = registry.render()

    assert 'route="/v1/repos/{repo_id}"' in output
    assert 'method="GET"' in output
    assert "http_request_duration_seconds_count" in output
    assert "question" not in output


def test_github_signature_verification_uses_raw_body():
    body = b'{"zen":"Keep it logically awesome."}'
    secret = "test-webhook-secret"
    signature = "sha256=bb1d1a3b3b2db3c8d79f2e1c26e0ed8f6db1b8a3c4dd1de3e1c2d2e4edb7e564"

    # The fixed value above is intentionally not trusted as a valid signature.
    assert not verify_hmac_signature(secret, body, signature)
    import hashlib
    import hmac

    valid = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_hmac_signature(secret, body, valid)
    assert not verify_hmac_signature(secret, body + b" ", valid)


def test_b9_routes_are_present_in_openapi(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://cartographer:cartographer@localhost:55432/cartographer"
    )
    from app.main import app

    paths = app.openapi()["paths"]
    assert "/metrics" in paths
    assert "/v1/admin/stats" in paths
    assert "/v1/admin/queries" in paths
    assert "/v1/webhooks/github" in paths
    assert {"APIKeyHeader": []} in paths["/v1/admin/stats"]["get"]["security"]
    assert {"HTTPBearer": []} in paths["/v1/admin/stats"]["get"]["security"]
