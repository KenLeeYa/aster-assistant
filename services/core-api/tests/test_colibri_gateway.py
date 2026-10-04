import httpx
import pytest
from ky_jarvis_core.agents.providers import ColibriGatewayProvider, OllamaUnavailableError


@pytest.mark.asyncio
async def test_colibri_gateway_requires_local_and_parses_object() -> None:
    with pytest.raises(ValueError):
        ColibriGatewayProvider(base_url="https://remote.example", model="test")

    def responder(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"summary":"ok"}'}}]})

    provider = ColibriGatewayProvider(
        base_url="http://127.0.0.1:8321",
        model="local-test",
        transport=httpx.MockTransport(responder),
    )
    assert await provider.generate(system="system", user="user", schema={"type": "object"}) == {
        "summary": "ok"
    }


@pytest.mark.asyncio
async def test_colibri_gateway_rejects_unstructured_output() -> None:
    provider = ColibriGatewayProvider(
        base_url="http://127.0.0.1:8321",
        model="local-test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"choices": [{"message": {"content": "oops"}}]}
            )
        ),
    )
    with pytest.raises(OllamaUnavailableError):
        await provider.generate(system="system", user="user", schema={"type": "object"})
