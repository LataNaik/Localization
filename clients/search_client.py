"""REST client for fetching localizations from search API."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

import httpx

from models import LocalizationMessage, RequestInfo, SearchRequest, SearchResponse

logger = logging.getLogger(__name__)


class SearchClient:
    """Async HTTP client for searching and fetching localizations."""

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        request_info: Optional[RequestInfo] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.request_info = request_info or RequestInfo()
        self._client: Optional[httpx.AsyncClient] = None

    @classmethod
    def from_json_file(
        cls,
        base_url: str,
        json_path: str | Path,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> "SearchClient":
        """Create client with RequestInfo loaded from JSON file."""
        with open(json_path) as f:
            data = json.load(f)

        request_info = None
        if "RequestInfo" in data:
            request_info = RequestInfo(**data["RequestInfo"])

        return cls(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
            request_info=request_info,
        )

    def _get_headers(self) -> dict[str, str]:
        """Build request headers."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
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

    async def search(
        self,
        locale: str,
        module: Optional[str] = None,
        tenant_id: Optional[str] = None,
        codes: Optional[list[str]] = None,
    ) -> list[LocalizationMessage]:
        """
        Search for localizations.

        Args:
            locale: Locale code (e.g., en_MZ)
            module: Module name to filter by
            tenant_id: Tenant ID
            codes: Optional list of specific codes to search

        Returns:
            List of LocalizationMessage objects
        """
        # Build query params
        params = {"locale": locale}
        if module:
            params["module"] = module
        if tenant_id:
            params["tenantId"] = tenant_id
        if codes:
            params["codes"] = ",".join(codes)

        # Build request payload
        search_request = SearchRequest(
            request_info=self.request_info,
            tenantId=tenant_id,
            module=module,
            locale=locale,
        )

        logger.info(f"Searching localizations for locale: {locale}, module: {module}")

        response = await self._request_with_retry(
            "POST",
            "/localization/messages/v1/_search",
            params=params,
            json=search_request.model_dump(mode="json", by_alias=True, exclude_none=True),
        )
        data = response.json()

        # Parse response
        messages = []
        if "messages" in data:
            messages = [LocalizationMessage(**msg) for msg in data["messages"]]
        elif isinstance(data, list):
            messages = [LocalizationMessage(**msg) for msg in data]

        logger.info(f"Found {len(messages)} localizations")
        return messages

    async def get_all(
        self,
        locale: str,
        tenant_id: str,
        module: Optional[str] = None,
    ) -> list[LocalizationMessage]:
        """Fetch all localizations for a locale and tenant."""
        return await self.search(
            locale=locale,
            module=module,
            tenant_id=tenant_id,
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "SearchClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
