"""Pydantic models for localization data."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class Role(BaseModel):
    """User role model."""

    name: str
    code: str
    tenantId: str


class UserInfo(BaseModel):
    """User information model."""

    id: Optional[int] = None
    uuid: Optional[str] = None
    userName: Optional[str] = None
    name: Optional[str] = None
    mobileNumber: Optional[str] = None
    emailId: Optional[str] = None
    locale: Optional[str] = None
    type: Optional[str] = None
    roles: list[Role] = Field(default_factory=list)
    active: Optional[bool] = None
    tenantId: Optional[str] = None
    permanentCity: Optional[str] = None


class RequestInfo(BaseModel):
    """Request info wrapper for API calls."""

    apiId: str = "Rainmaker"
    ver: str = ".01"
    ts: str = ""
    action: str = "_search"
    did: str = "1"
    key: str = ""
    msgId: str = "20170310130900|en_IN"
    authToken: Optional[str] = None
    userInfo: Optional[UserInfo] = None


class LocalizationMessage(BaseModel):
    """Individual localization message."""

    code: str = Field(..., description="Localization key/code")
    message: str = Field(..., description="Localized value/text")
    module: str = Field(..., description="Module name")
    locale: str = Field(..., description="Locale code (e.g., en_MZ)")


class Localization(BaseModel):
    """Core localization data model (legacy compatibility)."""

    id: Optional[str] = Field(default=None, description="Unique identifier")
    key: str = Field(..., description="Localization key")
    value: str = Field(..., description="Localized value/text")
    locale: str = Field(..., description="Locale code (e.g., en-US, fr-FR)")
    namespace: Optional[str] = Field(default=None, description="Namespace or category")
    metadata: Optional[dict[str, Any]] = Field(default=None, description="Additional metadata")
    created_at: Optional[datetime] = Field(default=None, description="Creation timestamp")
    updated_at: Optional[datetime] = Field(default=None, description="Last update timestamp")

    def to_message(self, module: str) -> LocalizationMessage:
        """Convert to LocalizationMessage format."""
        return LocalizationMessage(
            code=self.key,
            message=self.value,
            module=module,
            locale=self.locale,
        )


class SearchRequest(BaseModel):
    """Search API request payload."""

    model_config = ConfigDict(populate_by_name=True)

    request_info: RequestInfo = Field(default_factory=RequestInfo, alias="RequestInfo")
    tenantId: Optional[str] = None
    module: Optional[str] = None
    locale: Optional[str] = None


class SearchResponse(BaseModel):
    """API response wrapper for search results."""

    messages: list[LocalizationMessage] = Field(default_factory=list)
    tenantId: Optional[str] = None

    # Legacy fields for compatibility
    data: list[Localization] = Field(default_factory=list, description="List of localizations")
    total: int = Field(default=0, description="Total number of results")
    page: int = Field(default=1, description="Current page number")
    page_size: int = Field(default=100, description="Number of items per page")
    has_more: bool = Field(default=False, description="Whether more pages exist")


class UpsertRequest(BaseModel):
    """POST request body for upserting localizations."""

    model_config = ConfigDict(populate_by_name=True)

    request_info: RequestInfo = Field(alias="RequestInfo")
    tenantId: str
    module: str
    locale: str
    messages: list[LocalizationMessage]


class UpsertResult(BaseModel):
    """Response from upsert operation."""

    success: bool = Field(default=True, description="Whether the operation succeeded")
    created: int = Field(default=0, description="Number of records created")
    updated: int = Field(default=0, description="Number of records updated")
    failed: int = Field(default=0, description="Number of records that failed")
    errors: list[str] = Field(default_factory=list, description="List of error messages")
    messages: list[LocalizationMessage] = Field(default_factory=list)


class SyncResult(BaseModel):
    """Result of a full sync operation."""

    success: bool = Field(default=True, description="Whether the sync succeeded")
    source_count: int = Field(default=0, description="Number of items fetched from source")
    target_environment: str = Field(default="", description="Target environment name")
    upsert_results: list[UpsertResult] = Field(
        default_factory=list, description="Results from upsert operations"
    )
    total_created: int = Field(default=0, description="Total records created")
    total_updated: int = Field(default=0, description="Total records updated")
    total_failed: int = Field(default=0, description="Total records that failed")
    duration_seconds: float = Field(default=0.0, description="Duration of sync in seconds")
    error: Optional[str] = Field(default=None, description="Error message if sync failed")


class AuthRequest(BaseModel):
    """Authentication request model."""

    username: str = Field(..., description="Username")
    password: str = Field(..., description="Password")
    tenant_id: str = Field(..., description="Tenant ID")
    user_type: str = Field(default="EMPLOYEE", description="User type")
    grant_type: str = Field(default="password", description="OAuth grant type")
    scope: str = Field(default="read", description="OAuth scope")


class AuthResponse(BaseModel):
    """Authentication response model."""

    access_token: Optional[str] = Field(None, description="OAuth access token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: Optional[int] = Field(None, description="Token expiry in seconds")
    refresh_token: Optional[str] = Field(None, description="Refresh token")
    scope: Optional[str] = Field(None, description="OAuth scope")
    user_info: Optional[dict[str, Any]] = Field(None, description="User information from response")
