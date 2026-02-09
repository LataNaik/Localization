"""REST client for upserting localizations to target environments."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

import httpx

from models import LocalizationMessage, RequestInfo, UserInfo, UpsertRequest, UpsertResult

logger = logging.getLogger(__name__)


class UpsertClient:
    """Async HTTP client for upserting localizations."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 60.0,
        max_retries: int = 3,
        request_info: Optional[RequestInfo] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.request_info = request_info or RequestInfo()
        self._client: Optional[httpx.AsyncClient] = None

    @classmethod
    def from_json_file(
        cls,
        base_url: str,
        json_path: str | Path,
        timeout: float = 60.0,
        max_retries: int = 3,
    ) -> "UpsertClient":
        """Create client with RequestInfo loaded from JSON file."""
        with open(json_path) as f:
            data = json.load(f)

        request_info = None
        if "RequestInfo" in data:
            ri_data = data["RequestInfo"]
            user_info = None
            if ri_data.get("userInfo"):
                user_info = UserInfo(**ri_data["userInfo"])
            request_info = RequestInfo(
                apiId=ri_data.get("apiId", "Rainmaker"),
                ver=ri_data.get("ver", ".01"),
                ts=ri_data.get("ts", ""),
                action=ri_data.get("action", "_create"),
                did=ri_data.get("did", "1"),
                key=ri_data.get("key", ""),
                msgId=ri_data.get("msgId", ""),
                authToken=ri_data.get("authToken"),
                userInfo=user_info,
            )

        return cls(
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            request_info=request_info,
        )

    def set_auth_token(self, token: str) -> None:
        """Set the authentication token."""
        self.request_info.authToken = token

    def _get_headers(self) -> dict[str, str]:
        """Build request headers."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self._get_headers(),
                timeout=self.timeout,
            )
        return self._client

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """Make HTTP request with exponential backoff retry."""
        client = await self._get_client()
        last_exception = None

        for attempt in range(self.max_retries):
            try:
                response = await client.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as e:
                if e.response.status_code < 500:
                    raise
                last_exception = e
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_exception = e

            if attempt < self.max_retries - 1:
                wait_time = 2**attempt
                logger.warning(
                    f"Request failed (attempt {attempt + 1}/{self.max_retries}), "
                    f"retrying in {wait_time}s..."
                )
                await asyncio.sleep(wait_time)

        raise last_exception or Exception("Request failed after retries")

    async def upsert(
        self,
        messages: list[LocalizationMessage],
        tenant_id: str,
        module: str,
        locale: str,
    ) -> UpsertResult:
        """
        Upsert a list of localization messages.

        Args:
            messages: List of LocalizationMessage objects
            tenant_id: Tenant ID
            module: Module name
            locale: Locale code

        Returns:
            UpsertResult with operation details
        """
        if not messages:
            return UpsertResult(success=True, created=0, updated=0, failed=0)

        request = UpsertRequest(
            request_info=self.request_info,
            tenantId=tenant_id,
            module=module,
            locale=locale,
            messages=messages,
        )

        logger.info(f"Upserting {len(messages)} localizations to {tenant_id}/{module}/{locale}")

        try:
            response = await self._request_with_retry(
                "POST",
                "/localization/messages/v1/_upsert",
                json=request.model_dump(mode="json", by_alias=True, exclude_none=True),
            )
            data = response.json()

            # Parse response
            result_messages = []
            if "messages" in data:
                result_messages = [LocalizationMessage(**msg) for msg in data["messages"]]

            return UpsertResult(
                success=True,
                created=len(result_messages),
                updated=0,
                failed=0,
                messages=result_messages,
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"Upsert failed: {e}")
            error_msg = str(e)
            try:
                error_data = e.response.json()
                if "Errors" in error_data:
                    error_msg = "; ".join(err.get("message", str(err)) for err in error_data["Errors"])
            except Exception:
                pass

            return UpsertResult(
                success=False,
                failed=len(messages),
                errors=[error_msg],
            )

    async def upsert_batch(
        self,
        messages: list[LocalizationMessage],
        tenant_id: str,
        module: str,
        locale: str,
        batch_size: int = 100,
    ) -> list[UpsertResult]:
        """Upsert localizations in batches for efficiency."""
        if not messages:
            return []

        results: list[UpsertResult] = []
        total_batches = (len(messages) + batch_size - 1) // batch_size

        for i in range(0, len(messages), batch_size):
            batch = messages[i : i + batch_size]
            batch_num = i // batch_size + 1
            logger.info(f"Processing batch {batch_num}/{total_batches}...")

            result = await self.upsert(
                messages=batch,
                tenant_id=tenant_id,
                module=module,
                locale=locale,
            )
            results.append(result)

            if not result.success:
                logger.warning(f"Batch {batch_num} had failures: {result.errors}")

        return results

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "UpsertClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
