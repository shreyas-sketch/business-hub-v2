"""The live AI engines and WhatsApp/SMS senders, exercised against fake HTTP servers (no real keys needed)."""
import json

import httpx
import pytest

from app import messaging
from app.ai import provider, tasks
from app.ai.provider import AIError
from app.config import settings
from tests.conftest import PROFILE, login


REAL_CLIENT = httpx.AsyncClient


class FakeHTTP:
    """Stands in for httpx.AsyncClient inside the app; records requests and answers from a handler."""
    def __init__(self, handler):
        self.handler, self.calls = handler, []

    def __call__(self, *a, **k):
        def respond(req):
            self.calls.append(req)
            return self.handler(req)
        return REAL_CLIENT(transport=httpx.MockTransport(respond), timeout=5)


@pytest.fixture
def ai(monkeypatch):
    def use(name):
        object.__setattr__(settings, "ai_provider", name)
        object.__setattr__(settings, "anthropic_api_key", "sk-test")
    yield use
    object.__setattr__(settings, "ai_provider", "mock")


async def test_anthropic_call_shape_and_usage(ai, monkeypatch):
    ai("anthropic")
    def handler(req):
        body = json.loads(req.content)
        assert req.url.path == "/v1/messages" and req.headers["x-api-key"] == "sk-test" and req.headers["anthropic-version"] == "2023-06-01"
        assert body["model"] == "claude-haiku-5-5" and "Shree Ganesh Interiors" in body["messages"][0]["content"]
        assert body["output_config"] == {"effort": "low"} and body["max_tokens"] > 4000  # room for thinking
        assert "thinking" not in body and "temperature" not in body
        return httpx.Response(200, json={"content": [{"type": "text", "text": '```json\n{"options": [{"message": "Kitchens done on time", "pitch": "We fit kitchens."}]}\n```'}],
                                         "usage": {"input_tokens": 900, "output_tokens": 200}})
    fake = FakeHTTP(handler); monkeypatch.setattr(provider.httpx, "AsyncClient", fake)
    result, usage = await tasks.brand_message(PROFILE)
    assert result["options"][0]["message"] == "Kitchens done on time" and usage.input_tokens == 900
    assert provider.cost_inr(usage) == round(900 / 1e6 * 85 + 200 / 1e6 * 425, 4)


async def test_engine_errors_become_aierror(ai, monkeypatch):
    ai("anthropic")
    monkeypatch.setattr(provider.httpx, "AsyncClient", FakeHTTP(lambda r: httpx.Response(529, json={"error": {"message": "overloaded"}})))
    with pytest.raises(AIError):
        await tasks.business_qa(PROFILE, "What next?")
    monkeypatch.setattr(provider.httpx, "AsyncClient", FakeHTTP(lambda r: httpx.Response(200, json={"content": [{"type": "text", "text": "Sorry, I can't"}], "usage": {}})))
    with pytest.raises(AIError):
        await tasks.business_qa(PROFILE, "What next?")
    for stop in ("max_tokens", "refusal"):  # a cut-off or declined answer is an error, never half a JSON object
        monkeypatch.setattr(provider.httpx, "AsyncClient", FakeHTTP(lambda r, stop=stop: httpx.Response(200, json={
            "content": [{"type": "text", "text": '{"answer": "ok"}'}], "stop_reason": stop, "usage": {}})))
        with pytest.raises(AIError):
            await tasks.business_qa(PROFILE, "What next?")


async def test_incomplete_ai_website_is_refused_and_refunded(client, ai, monkeypatch):
    await login(client, "9826011111")
    await client.put("/api/business", json=PROFILE)
    ai("anthropic")
    monkeypatch.setattr(provider.httpx, "AsyncClient", FakeHTTP(lambda r: httpx.Response(200, json={"content": [{"type": "text", "text": '{"headline": ""}'}], "usage": {}})))
    left = (await client.get("/api/me")).json()["runs"]["left"]
    r = await client.post("/api/site/generate")
    assert r.status_code == 502 and "not used" in r.json()["detail"]
    assert (await client.get("/api/site")).json() == {}
    assert (await client.get("/api/me")).json()["runs"]["left"] == left  # the owner's run came back


async def test_ai_nulls_are_read_as_blanks(client, ai, monkeypatch):
    await login(client, "9826022222")
    await client.put("/api/business", json=PROFILE)
    ai("anthropic")
    draft = {"headline": "Kitchens on time", "subheadline": None, "offers": [{"name": "Modular kitchen", "description": None, "price": None}],
             "why": None, "faq": [{"q": "Do you visit?", "a": "Yes"}]}
    monkeypatch.setattr(provider.httpx, "AsyncClient", FakeHTTP(lambda r: httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps(draft)}], "usage": {}})))
    r = await client.post("/api/site/generate")
    assert r.status_code == 200, r.text
    assert r.json()["content"]["offers"][0]["price"] == "" and r.json()["content"]["why"] == []


async def test_whatsapp_params_are_cleaned_for_meta(monkeypatch):
    object.__setattr__(settings, "aisensy_api_key", "ais-key")
    try:
        sent = []
        def handler(req):
            sent.append(json.loads(req.content)); return httpx.Response(200)
        monkeypatch.setattr(messaging.httpx, "AsyncClient", FakeHTTP(handler))
        await messaging.whatsapp_template("+919820000000", "lead_alert", "Asha", ["Shree Ganesh", "Ravi", "+919833000000", "Need a quote\n\nfor 2BHK\t   asap", ""], "lead_alert")
        assert sent[0]["templateParams"] == ["Shree Ganesh", "Ravi", "+919833000000", "Need a quote for 2BHK asap", "-"]
        assert "buttons" not in sent[0]
    finally:
        object.__setattr__(settings, "aisensy_api_key", "")


async def test_gemini_and_openai_shapes(ai, monkeypatch):
    for name, check, reply in [
        ("gemini", lambda r: r.url.path.endswith(":generateContent") and "x-goog-api-key" in r.headers,
         {"candidates": [{"content": {"parts": [{"text": '{"answer": "Do X"}'}]}}], "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 3}}),
        ("openai", lambda r: r.url.path == "/v1/chat/completions" and r.headers["authorization"].startswith("Bearer"),
         {"choices": [{"message": {"content": '{"answer": "Do X"}'}}], "usage": {"prompt_tokens": 5, "completion_tokens": 3}}),
    ]:
        ai(name)
        monkeypatch.setattr(provider.httpx, "AsyncClient", FakeHTTP(lambda r, c=check, rep=reply: (httpx.Response(200, json=rep) if c(r) else httpx.Response(400))))
        result, usage = await tasks.business_qa(PROFILE, "What next?")
        assert result == {"answer": "Do X"} and usage.output_tokens == 3


async def test_aisensy_payload_and_sms_fallback(monkeypatch):
    for k, v in {"aisensy_api_key": "ais-key", "aisensy_otp_campaign": "lw_otp", "msg91_auth_key": "m91", "msg91_otp_template_id": "tpl"}.items():
        object.__setattr__(settings, k, v)
    try:
        def handler(req):
            if "aisensy" in req.url.host:
                body = json.loads(req.content)
                assert body == {"apiKey": "ais-key", "campaignName": "lw_otp", "destination": "919820000000", "userName": "there",
                                "templateParams": ["123456"], "source": "action-hub",
                                "buttons": [{"type": "button", "sub_type": "url", "index": 0, "parameters": [{"type": "text", "text": "123456"}]}]}
                return httpx.Response(500)  # WhatsApp down → must fall back to SMS
            assert req.url.host == "control.msg91.com" and req.headers["authkey"] == "m91"
            assert dict(req.url.params) == {"template_id": "tpl", "mobile": "919820000000", "otp": "123456"}
            return httpx.Response(200, json={"type": "success"})
        fake = FakeHTTP(handler); monkeypatch.setattr(messaging.httpx, "AsyncClient", fake)
        assert await messaging.send_otp("+919820000000", "123456") == {"sent": True, "via": "sms"}
        assert len(fake.calls) == 2
    finally:
        for k in ("aisensy_api_key", "aisensy_otp_campaign", "msg91_auth_key", "msg91_otp_template_id"):
            object.__setattr__(settings, k, "")


async def test_demo_drafts_read_cleanly_with_a_minimal_profile():
    """Owners often skip the optional questions; demo drafts must still read like proper sentences."""
    p = {"name": "Joshi Sweets", "industry": "Mithai and farsan shop", "city": "", "ideal_customer": "", "why_us": "", "offers": []}
    texts = []
    for result, _ in [await tasks.brand_message(p), await tasks.site_content(p, None), await tasks.social_posts(p, ""),
                      await tasks.reply_draft(p, "Price for 1 kg kaju katli?"), await tasks.business_qa(p, "How to sell more on Diwali?")]:
        texts.append(json.dumps(result, ensure_ascii=False))
    blob = " ".join(texts)
    for bad in ["  ", " .", " ,", "the  ", "of the in", "None", "{", "with  "]:
        assert bad not in blob.replace('{"', "").replace('": {', "").replace("{", "") if bad == "{" else bad not in blob, bad
