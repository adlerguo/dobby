from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from app.core.config import settings


@dataclass
class WanwuLoginResult:
    token: str
    org_id: str | None = None


class WanwuBFFClient:
    def __init__(self, base_url: str | None = None, api_prefix: str = "/v1") -> None:
        self.base_url = (base_url or settings.wanwu_bff_base_url).rstrip("/")
        self.api_prefix = api_prefix.rstrip("/")
        self._token: str | None = settings.wanwu_svc_token
        self._org_id: str | None = None

    def _url(self, path: str) -> str:
        return f"{self.base_url}{self.api_prefix}{path}"

    async def health_probe(self) -> dict[str, str | int | bool]:
        # BFF 当前没有稳定公开的 health 契约；这里只保留阶段 2 调用封装入口。
        async with httpx.AsyncClient(timeout=settings.wanwu_bff_timeout_seconds) as client:
            response = await client.get(f"{self.base_url}/")
            return {
                "ok": response.status_code < 500,
                "status_code": response.status_code,
                "base_url": self.base_url,
            }

    async def login(self) -> WanwuLoginResult:
        if self._token:
            return WanwuLoginResult(token=self._token, org_id=self._org_id)
        if not settings.wanwu_svc_username or not settings.wanwu_svc_password:
            raise RuntimeError("wanwu_service_account_not_configured")

        async with httpx.AsyncClient(timeout=settings.wanwu_bff_timeout_seconds) as client:
            rsa_resp = await self._request_json(client, "GET", "/base/rsa/public-key")
            key_id = rsa_resp["keyId"]
            public_key = rsa_resp["publicKey"]
            challenge = rsa_resp["challenge"]
            cipher = _rsa_encrypt_password(settings.wanwu_svc_password, public_key, challenge)

            captcha_key = settings.wanwu_svc_captcha_key
            captcha_code = settings.wanwu_svc_captcha_code
            if not captcha_key or not captcha_code:
                captcha_resp = await self._request_json(client, "GET", "/base/captcha")
                captcha_key = captcha_key or captcha_resp.get("key")
                # 正式环境不会返回明文验证码；若没有环境变量，调用方需要人工识别后重试。
                captcha_code = captcha_code or captcha_resp.get("code")
            if not captcha_key or not captcha_code:
                raise RuntimeError("wanwu_captcha_required")

            login_resp = await self._request_json(
                client,
                "POST",
                "/base/login",
                json={
                    "username": settings.wanwu_svc_username,
                    "cipher": cipher,
                    "keyId": key_id,
                    "key": captcha_key,
                    "code": captcha_code,
                },
            )

        token = login_resp.get("token")
        if not token:
            raise RuntimeError("wanwu_login_token_missing")
        self._token = str(token)
        self._org_id = _extract_org_id(login_resp)
        return WanwuLoginResult(token=self._token, org_id=self._org_id)

    async def list_assistants_with_token(
        self,
        user_token: str,
        org_id: str | None,
        name: str | None = None,
    ) -> Any:
        headers = self._auth_headers(user_token, org_id)
        async with httpx.AsyncClient(timeout=settings.wanwu_bff_timeout_seconds) as client:
            response = await client.get(self._url("/assistant/select"), params={"name": name or ""}, headers=headers)
            self._raise_for_error(response)
            return _unwrap_response(response.json())

    async def stream_draft_assistant(
        self,
        assistant_id: str,
        prompt: str,
        org_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> AsyncIterator[str]:
        login = await self.login()
        headers = self._auth_headers(login.token, org_id or login.org_id)
        payload = {
            "assistantId": assistant_id,
            "conversationId": "",
            "fileInfo": [],
            "prompt": prompt,
            "systemPrompt": "",
            "isCompare": False,
            "sseHold": False,
        }
        timeout = httpx.Timeout(timeout_seconds or settings.eval_timeout_seconds, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", self._url("/assistant/stream/draft"), json=payload, headers=headers) as response:
                self._refresh_token_from_headers(response.headers)
                self._raise_for_error(response)
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        yield line.removeprefix("data:").strip()

    async def _request_json(self, client: httpx.AsyncClient, method: str, path: str, **kwargs) -> dict[str, Any]:
        response = await client.request(method, self._url(path), **kwargs)
        self._refresh_token_from_headers(response.headers)
        self._raise_for_error(response)
        return _unwrap_response(response.json())

    def _auth_headers(self, token: str, org_id: str | None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "x-client-id": "cockpit-service",
        }
        if org_id:
            headers["x-org-id"] = org_id
        return headers

    def _refresh_token_from_headers(self, headers: httpx.Headers) -> None:
        new_token = headers.get("new-token") or headers.get("New-Token")
        if new_token:
            self._token = new_token

    def _raise_for_error(self, response: httpx.Response) -> None:
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return
        data = response.json()
        code = data.get("code")
        if code not in (None, 0):
            raise RuntimeError(str(data.get("message") or data.get("msg") or f"wanwu_error_{code}"))


def _unwrap_response(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    if data is None:
        return {}
    return {"items": data}


def _extract_org_id(login_resp: dict[str, Any]) -> str | None:
    org_permission = login_resp.get("orgPermission")
    if isinstance(org_permission, dict):
        org_id = org_permission.get("orgId") or org_permission.get("id")
        if org_id:
            return str(org_id)
    orgs = login_resp.get("orgs")
    if isinstance(orgs, list) and orgs:
        org = orgs[0]
        if isinstance(org, dict):
            org_id = org.get("id") or org.get("orgId")
            if org_id:
                return str(org_id)
    return None


def _rsa_encrypt_password(password: str, public_key_pem: str, challenge: str) -> str:
    plaintext = json.dumps({"password": password, "challenge": challenge}, separators=(",", ":")).encode()
    public_key = serialization.load_pem_public_key(public_key_pem.encode())
    encrypted = public_key.encrypt(
        plaintext,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return base64.b64encode(encrypted).decode()
