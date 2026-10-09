"""DEMO_PHONES on a test deployment: only the listed numbers get their code on screen; every other number still needs
WhatsApp or SMS, and nothing leaks the code for them."""
from app.config import settings


def _set(**kv):
    old = {k: getattr(settings, k) for k in kv}
    for k, v in kv.items():
        object.__setattr__(settings, k, v)
    return old


async def test_demo_number_sees_its_code_and_logs_in_on_a_real_deployment(client):
    old = _set(env="production", demo_phones=("+919820000001",))
    try:
        r = await client.post("/api/auth/otp", json={"phone": "98200 00001"})
        assert r.status_code == 200
        body = r.json()
        assert body["via"] == "demo" and len(body["dev_code"]) == 6
        v = await client.post("/api/auth/verify", json={"phone": "9820000001", "code": body["dev_code"]})
        assert v.status_code == 200

        # Any other number goes through the normal channels — with none configured it fails, and never shows a code.
        r = await client.post("/api/auth/otp", json={"phone": "9820000099"})
        assert r.status_code == 503 and "dev_code" not in r.text
    finally:
        _set(**old)


async def test_no_demo_numbers_by_default():
    assert settings.demo_phones == ()
