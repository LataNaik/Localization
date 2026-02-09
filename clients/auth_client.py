"""REST client for authentication."""

import logging
from typing import Optional

import httpx

from models import AuthRequest, AuthResponse

logger = logging.getLogger(__name__)


class AuthClient:
    """Client for OAuth token authentication."""

    def __init__(
        self,
        auth_url: str,
        client_credentials: str = "ZWdvdi11c2VyLWNsaWVudDo=",
        timeout: float = 30.0,
    ):
        """
        Initialize auth client.

        Args:
            auth_url: OAuth token endpoint URL
            client_credentials: Base64 encoded client credentials for Basic auth
            timeout: Request timeout in seconds
        """
        self.auth_url = auth_url
        self.client_credentials = client_credentials
        self.timeout = timeout

    async def get_token(
        self,
        username: str,
        password: str,
        tenant_id: str,
        user_type: str = "EMPLOYEE",
        grant_type: str = "password",
        scope: str = "read",
    ) -> AuthResponse:
        """
        Get OAuth access token.

        Args:
            username: User username
            password: User password
            tenant_id: Tenant ID
            user_type: User type (EMPLOYEE, CITIZEN, etc.)
            grant_type: OAuth grant type
            scope: OAuth scope

        Returns:
            AuthResponse with access token and user info
        """
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Authorization": f"Basic {self.client_credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        data = {
            "username": username,
            "password": password,
            "grant_type": grant_type,
            "scope": scope,
            "tenantId": tenant_id,
            "userType": user_type,
        }

        logger.info(f"Authenticating user: {username} for tenant: {tenant_id}")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self.auth_url,
                headers=headers,
                data=data,
            )
            response.raise_for_status()
            result = response.json()

        auth_response = AuthResponse(
            access_token=result.get("access_token"),
            token_type=result.get("token_type", "bearer"),
            expires_in=result.get("expires_in"),
            refresh_token=result.get("refresh_token"),
            scope=result.get("scope"),
            user_info=result.get("UserRequest"),
        )

        logger.info(f"Authentication successful for user: {username}")
        return auth_response

    async def get_token_from_request(self, request: AuthRequest) -> AuthResponse:
        """Get token using AuthRequest model."""
        return await self.get_token(
            username=request.username,
            password=request.password,
            tenant_id=request.tenant_id,
            user_type=request.user_type,
            grant_type=request.grant_type,
            scope=request.scope,
        )
