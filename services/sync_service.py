"""Orchestration service for syncing localizations between environments."""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from clients import AuthClient, SearchClient, UpsertClient
from config import Settings
from models import AuthResponse, LocalizationMessage, RequestInfo, SyncResult, UserInfo

logger = logging.getLogger(__name__)


class SyncService:
    """Service to orchestrate localization sync between environments."""

    def __init__(
        self,
        settings: Settings,
        requests_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ):
        self.settings = settings
        self.requests_dir = requests_dir or Path("requests")
        self.output_dir = output_dir or Path("output")
        self._auth_token: Optional[str] = None
        self._user_info: Optional[dict] = None

    def _save_to_file(self, data: dict | list, filename: str) -> Path:
        """Save data as JSON to the output directory."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.output_dir / filename
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved output to {file_path}")
        return file_path

    def _update_upsert_request_file(
        self,
        request_info: RequestInfo,
        tenant_id: str,
        module: str,
        locale: str,
        messages: list[LocalizationMessage],
    ) -> None:
        """Update requests/upsert.json with the actual request payload."""
        file_path = self.requests_dir / "upsert.json"
        payload = {
            "RequestInfo": request_info.model_dump(mode="json", exclude_none=True),
            "tenantId": tenant_id,
            "module": module,
            "locale": locale,
            "messages": [msg.model_dump(mode="json") for msg in messages],
        }
        with open(file_path, "w") as f:
            json.dump(payload, f, indent=4, ensure_ascii=False)
        logger.info(f"Updated {file_path} with actual upsert request")

    def _load_request_info(self, json_file: str) -> Optional[RequestInfo]:
        """Load RequestInfo from a JSON file in requests directory."""
        file_path = self.requests_dir / json_file
        if not file_path.exists():
            logger.warning(f"Request file not found: {file_path}")
            return None

        with open(file_path) as f:
            data = json.load(f)

        if "RequestInfo" not in data:
            return None

        ri_data = data["RequestInfo"]
        user_info = None
        if ri_data.get("userInfo"):
            user_info = UserInfo(**ri_data["userInfo"])

        return RequestInfo(
            apiId=ri_data.get("apiId", "Rainmaker"),
            ver=ri_data.get("ver", ".01"),
            ts=ri_data.get("ts", ""),
            action=ri_data.get("action", "_search"),
            did=ri_data.get("did", "1"),
            key=ri_data.get("key", ""),
            msgId=ri_data.get("msgId", ""),
            authToken=ri_data.get("authToken"),
            userInfo=user_info,
        )

    async def authenticate(
        self,
        env: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> AuthResponse:
        """Authenticate and get access token for a specific environment."""
        auth_url = self.settings.get_auth_url(env)
        resolved_tenant = tenant_id or self.settings.get_tenant_id(env)
        logger.info(f"Authenticating against {env}: {auth_url}")

        auth_client = AuthClient(
            auth_url=auth_url,
            client_credentials=self.settings.auth_client_credentials,
        )

        auth_response = await auth_client.get_token(
            username=username or self.settings.auth_username,
            password=password or self.settings.auth_password,
            tenant_id=resolved_tenant,
        )

        self._auth_token = auth_response.access_token
        self._user_info = auth_response.user_info
        logger.info("Authentication successful, token stored")

        return auth_response

    async def fetch_and_save(
        self,
        source_env: str,
        lang: str,
        module: Optional[str] = None,
        target_env: Optional[str] = None,
    ) -> tuple[list[LocalizationMessage], Path, Optional[Path]]:
        """
        Fetch localizations from source env and save response to file.
        Optionally transform locale and save the upsert-ready body.

        Args:
            source_env: Source environment to search from
            lang: Language code (en, fr, pt)
            module: Optional module name filter
            target_env: Target environment (for locale mapping)

        Returns:
            Tuple of (messages, search_response_path, upsert_body_path)
        """
        source_url = self.settings.get_api_url(source_env)
        source_key = self.settings.get_api_key(source_env)
        source_tenant = self.settings.get_tenant_id(source_env)
        source_locale = self.settings.get_locale(source_env, lang)

        # Load request info
        search_request_info = self._load_request_info("search.json")
        if self._auth_token and search_request_info:
            search_request_info.authToken = self._auth_token

        # Fetch from source env
        async with SearchClient(
            base_url=source_url,
            api_key=source_key,
            request_info=search_request_info,
        ) as search_client:
            messages = await search_client.search(
                locale=source_locale,
                module=module,
                tenant_id=source_tenant,
            )

        logger.info(f"Fetched {len(messages)} localizations from {source_env}")

        # Save raw search response
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        search_data = {
            "messages": [msg.model_dump() for msg in messages],
            "tenantId": source_tenant,
            "locale": source_locale,
            "module": module,
            "sourceEnv": source_env,
            "fetchedAt": timestamp,
            "totalCount": len(messages),
        }
        search_file = self._save_to_file(
            search_data, f"{timestamp}_search_response_{source_env}_{source_locale}.json"
        )

        # Transform locale and save upsert-ready body if target env is specified
        upsert_file = None
        if target_env:
            target_locale = self.settings.get_locale(target_env, lang)
            target_tenant = self.settings.get_tenant_id(target_env)

            transformed_messages = [
                LocalizationMessage(
                    code=msg.code,
                    message=msg.message,
                    module=msg.module,
                    locale=target_locale,
                )
                for msg in messages
            ]
            upsert_data = {
                "tenantId": target_tenant,
                "module": module or (messages[0].module if messages else ""),
                "locale": target_locale,
                "messages": [msg.model_dump() for msg in transformed_messages],
                "sourceEnv": source_env,
                "targetEnv": target_env,
                "totalCount": len(transformed_messages),
            }
            upsert_file = self._save_to_file(
                upsert_data, f"{timestamp}_upsert_body_{target_env}_{target_locale}.json"
            )
            messages = transformed_messages

        return messages, search_file, upsert_file

    async def upsert(
        self,
        source_env: str,
        target_env: str,
        lang: str,
        module: Optional[str] = None,
        batch_size: int = 100,
        auth_token: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> SyncResult:
        """
        Search localizations from source env, transform locale, and upsert to target env.

        Args:
            source_env: Source environment to search from
            target_env: Target environment to upsert to
            lang: Language code (en, fr, pt)
            module: Optional module name filter
            batch_size: Number of items per batch for upsert
            auth_token: Optional auth token (overrides authentication)
            username: Username for authentication
            password: Password for authentication

        Returns:
            SyncResult with operation details
        """
        start_time = time.time()

        source_url = self.settings.get_api_url(source_env)
        source_key = self.settings.get_api_key(source_env)
        source_tenant = self.settings.get_tenant_id(source_env)
        source_locale = self.settings.get_locale(source_env, lang)

        target_url = self.settings.get_upsert_url(target_env)
        target_key = self.settings.get_api_key(target_env) if not self.settings.is_localhost else None
        target_tenant = self.settings.get_tenant_id(target_env)
        target_locale = self.settings.get_locale(target_env, lang)

        upsert_target = f"localhost:{self.settings.localhost_port}" if self.settings.is_localhost else target_env
        logger.info(f"Upsert: {source_env} → {upsert_target}")
        logger.info(f"Source: {source_url} | tenant={source_tenant}, locale={source_locale}")
        logger.info(f"Target: {target_url} | tenant={target_tenant}, locale={target_locale}")
        logger.info(f"Module: {module or 'all'}")

        try:
            # Authenticate against target environment
            token = auth_token or self._auth_token
            if not token:
                logger.info(f"Logging in to {target_env}...")
                auth_response = await self.authenticate(
                    env=target_env,
                    username=username,
                    password=password,
                    tenant_id=target_tenant,
                )
                token = auth_response.access_token
                logger.info(f"Login to {target_env} successful")

            # Load request info from JSON files
            search_request_info = self._load_request_info("search.json")
            upsert_request_info = self._load_request_info("upsert.json")

            # Apply auth token
            if search_request_info:
                search_request_info.authToken = token
            if upsert_request_info:
                upsert_request_info.authToken = token

            # Search from source environment
            async with SearchClient(
                base_url=source_url,
                api_key=source_key,
                request_info=search_request_info,
            ) as search_client:
                logger.info(f"Fetching localizations from {source_env}...")
                messages = await search_client.search(
                    locale=source_locale,
                    module=module,
                    tenant_id=source_tenant,
                )

                source_count = len(messages)
                logger.info(f"Fetched {source_count} localizations from {source_env}")

                if not messages:
                    return SyncResult(
                        success=True,
                        source_count=0,
                        target_environment=target_env,
                        duration_seconds=time.time() - start_time,
                    )

                # Save raw search response
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                self._save_to_file(
                    {
                        "messages": [msg.model_dump() for msg in messages],
                        "tenantId": source_tenant,
                        "locale": source_locale,
                        "module": module,
                        "sourceEnv": source_env,
                        "totalCount": source_count,
                    },
                    f"{timestamp}_search_response_{source_env}_{source_locale}.json",
                )

                # Transform locale if different
                if target_locale != source_locale:
                    logger.info(f"Transforming locale: {source_locale} → {target_locale}")
                    messages = [
                        LocalizationMessage(
                            code=msg.code,
                            message=msg.message,
                            module=msg.module,
                            locale=target_locale,
                        )
                        for msg in messages
                    ]

                # Save transformed upsert request body
                upsert_module = module or messages[0].module
                self._save_to_file(
                    {
                        "tenantId": target_tenant,
                        "module": upsert_module,
                        "locale": target_locale,
                        "messages": [msg.model_dump() for msg in messages],
                        "targetEnv": target_env,
                        "totalCount": len(messages),
                    },
                    f"{timestamp}_upsert_body_{target_env}_{target_locale}.json",
                )

                # Update requests/upsert.json with actual payload
                if upsert_request_info:
                    self._update_upsert_request_file(
                        request_info=upsert_request_info,
                        tenant_id=target_tenant,
                        module=upsert_module,
                        locale=target_locale,
                        messages=messages,
                    )

                # Upsert to target environment
                async with UpsertClient(
                    base_url=target_url,
                    api_key=target_key,
                    request_info=upsert_request_info,
                ) as upsert_client:
                    upsert_results = await upsert_client.upsert_batch(
                        messages=messages,
                        tenant_id=target_tenant,
                        module=upsert_module,
                        locale=target_locale,
                        batch_size=batch_size,
                    )

                # Aggregate results
                total_created = sum(r.created for r in upsert_results)
                total_updated = sum(r.updated for r in upsert_results)
                total_failed = sum(r.failed for r in upsert_results)
                all_success = all(r.success for r in upsert_results)

                duration = time.time() - start_time
                logger.info(
                    f"Upsert completed in {duration:.2f}s - "
                    f"Created: {total_created}, Updated: {total_updated}, Failed: {total_failed}"
                )

                return SyncResult(
                    success=all_success,
                    source_count=source_count,
                    target_environment=target_env,
                    upsert_results=upsert_results,
                    total_created=total_created,
                    total_updated=total_updated,
                    total_failed=total_failed,
                    duration_seconds=duration,
                )

        except Exception as e:
            logger.exception(f"Upsert failed: {e}")
            return SyncResult(
                success=False,
                source_count=0,
                target_environment=target_env,
                duration_seconds=time.time() - start_time,
                error=str(e),
            )

    async def upsert_messages(
        self,
        target_env: str,
        messages: list[LocalizationMessage],
        tenant_id: str,
        module: str,
        locale: str,
        batch_size: int = 100,
        auth_token: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> SyncResult:
        """Upsert specific messages to target environment (from file)."""
        start_time = time.time()
        target_url = self.settings.get_upsert_url(target_env)
        target_key = self.settings.get_api_key(target_env) if not self.settings.is_localhost else None

        upsert_target = f"localhost:{self.settings.localhost_port}" if self.settings.is_localhost else target_env
        logger.info(f"Upserting {len(messages)} messages to {upsert_target}")

        try:
            # Authenticate against target environment
            token = auth_token or self._auth_token
            if not token:
                logger.info(f"Logging in to {target_env}...")
                auth_response = await self.authenticate(
                    env=target_env,
                    username=username,
                    password=password,
                    tenant_id=tenant_id,
                )
                token = auth_response.access_token
                logger.info(f"Login to {target_env} successful")

            upsert_request_info = self._load_request_info("upsert.json")
            if upsert_request_info:
                upsert_request_info.authToken = token

            # Update requests/upsert.json with actual payload
            if upsert_request_info:
                self._update_upsert_request_file(
                    request_info=upsert_request_info,
                    tenant_id=tenant_id,
                    module=module,
                    locale=locale,
                    messages=messages,
                )

            async with UpsertClient(
                base_url=target_url,
                api_key=target_key,
                request_info=upsert_request_info,
            ) as upsert_client:
                upsert_results = await upsert_client.upsert_batch(
                    messages=messages,
                    tenant_id=tenant_id,
                    module=module,
                    locale=locale,
                    batch_size=batch_size,
                )

            total_created = sum(r.created for r in upsert_results)
            total_updated = sum(r.updated for r in upsert_results)
            total_failed = sum(r.failed for r in upsert_results)
            all_success = all(r.success for r in upsert_results)

            duration = time.time() - start_time
            return SyncResult(
                success=all_success,
                source_count=len(messages),
                target_environment=target_env,
                upsert_results=upsert_results,
                total_created=total_created,
                total_updated=total_updated,
                total_failed=total_failed,
                duration_seconds=duration,
            )

        except Exception as e:
            logger.exception(f"Upsert failed: {e}")
            return SyncResult(
                success=False,
                source_count=len(messages),
                target_environment=target_env,
                duration_seconds=time.time() - start_time,
                error=str(e),
            )
