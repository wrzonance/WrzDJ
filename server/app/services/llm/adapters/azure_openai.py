"""Azure OpenAI adapter.

Azure OpenAI exposes the same Chat Completions *body* as the OpenAI Platform
API, but differs on two axes that prevent reusing the OpenAI-compatible code
path directly:

1. **URL** — per-deployment endpoint:
   ``https://<resource>.openai.azure.com/openai/deployments/<deployment>/chat/completions?api-version=<ver>``
2. **Auth header** — ``api-key: <key>`` (NOT ``Authorization: Bearer``).

We therefore build the URL + headers ourselves and only share the request-body
shaping (``_build_payload``) and response parsing (``parse_openai_response``)
with the OpenAI helper, plus the HTTP status → typed-exception mapping.

All configuration (resource name, deployment name, api version) **and** the
api key live in the encrypted ``credentials`` blob — there are no dedicated
columns. This lets admins rotate any of them via the existing
``PUT /credentials`` route without recreating the connector.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.services.llm.adapters._httpx_openai import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_TIMEOUT_SECONDS,
    _build_payload,
    _raise_for_status,
    build_healthcheck_request,
)
from app.services.llm.base import ChatRequest, ChatResponse, LlmAdapter
from app.services.llm.exceptions import AuthInvalid, ProviderUnavailable, ToolTranslationError
from app.services.llm.registry import register_adapter
from app.services.llm.tool_translation import parse_openai_response

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4o-mini"


def _build_azure_endpoint(resource_name: str, deployment_name: str, api_version: str) -> str:
    """Compose the per-deployment Azure Chat Completions URL.

    ``resource_name`` is the bare resource (e.g. ``my-co``), NOT a full host.
    """
    return (
        f"https://{resource_name}.openai.azure.com"
        f"/openai/deployments/{deployment_name}/chat/completions"
        f"?api-version={api_version}"
    )


class AzureOpenAIAdapter(LlmAdapter):
    connector_type = "azure_openai"

    def _extract_credentials(self) -> dict[str, str]:
        """Return the validated config dict from the encrypted blob.

        Keys: api_key, azure_resource_name, azure_deployment_name,
        azure_api_version.
        """
        raw = self.connector.credentials or ""
        try:
            blob = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise AuthInvalid("Connector credentials are malformed") from exc
        if not isinstance(blob, dict):
            raise AuthInvalid("Connector credentials shape is invalid")

        api_key = blob.get("api_key")
        resource = blob.get("azure_resource_name")
        deployment = blob.get("azure_deployment_name")
        api_version = blob.get("azure_api_version")
        if not (api_key and resource and deployment and api_version):
            raise AuthInvalid("Connector is missing Azure OpenAI configuration")
        return {
            "api_key": str(api_key),
            "azure_resource_name": str(resource),
            "azure_deployment_name": str(deployment),
            "azure_api_version": str(api_version),
        }

    async def _call(self, request: ChatRequest) -> ChatResponse:
        creds = self._extract_credentials()
        endpoint = _build_azure_endpoint(
            creds["azure_resource_name"],
            creds["azure_deployment_name"],
            creds["azure_api_version"],
        )

        # Azure routes by deployment, so the body `model` is largely cosmetic,
        # but the shared payload builder requires a non-None model. Default to
        # the deployment name when no explicit model/hint is supplied.
        model = request.model or self.connector.model_hint or creds["azure_deployment_name"]
        payload = _build_payload(request, model)

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "api-key": creds["api_key"],
        }

        timeout = request.timeout_seconds or DEFAULT_TIMEOUT_SECONDS
        timeout = min(max(timeout, 1.0), MAX_TIMEOUT_SECONDS)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(endpoint, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable("Upstream timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable("Upstream network error") from exc

        _raise_for_status(resp)

        try:
            body: Any = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ToolTranslationError("Upstream returned non-JSON body") from exc

        return parse_openai_response(body)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        return await self._call(request)

    async def health_check(self) -> None:
        # 1-token ping exercises the URL + api-key auth path.
        await self._call(build_healthcheck_request())


register_adapter("azure_openai", AzureOpenAIAdapter)
