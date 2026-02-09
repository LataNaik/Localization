"""Environment configuration using pydantic-settings."""

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Source and Target environments
    source_env: str = Field(default="qa", description="Source environment to search from")
    target_env: str = Field(default="uat", description="Target environment to upsert to")

    # Upsert mode: "auth" (remote TARGET_ENV) or "localhost"
    upsert_mode: str = Field(default="auth", description="Upsert mode: 'auth' or 'localhost'")
    localhost_port: int = Field(default=8765, description="Localhost port when upsert_mode=localhost")

    # Authentication (same credentials work for all environments)
    auth_client_credentials: str = Field(
        default="ZWdvdi11c2VyLWNsaWVudDo=",
        description="Base64 encoded client credentials for Basic auth",
    )
    auth_username: Optional[str] = Field(default=None, description="Default username")
    auth_password: Optional[str] = Field(default=None, description="Default password")

    # UAT Environment
    uat_api_url: Optional[str] = Field(default=None, description="UAT environment API URL")
    uat_tenant_id: str = Field(default="mz", description="Tenant ID for UAT")
    uat_locale_english: Optional[str] = Field(default="en_IN", description="English locale for UAT")
    uat_locale_french: Optional[str] = Field(default="fr_IN", description="French locale for UAT")
    uat_locale_portuguese: Optional[str] = Field(default="pt_IN", alias="uat_locale_portugueseh", description="Portuguese locale for UAT")

    # Demo Environment
    demo_api_url: Optional[str] = Field(default=None, description="Demo environment API URL")
    demo_tenant_id: str = Field(default="mz", description="Tenant ID for Demo")
    demo_locale_english: Optional[str] = Field(default="en_MZ", description="English locale for Demo")
    demo_locale_french: Optional[str] = Field(default="fr_MZ", description="French locale for Demo")
    demo_locale_portuguese: Optional[str] = Field(default="pt_MZ", alias="demo_locale_portugueseh", description="Portuguese locale for Demo")

    # QA Environment
    qa_api_url: Optional[str] = Field(default=None, description="QA environment API URL")
    qa_tenant_id: str = Field(default="mz", description="Tenant ID for QA")
    qa_locale_english: Optional[str] = Field(default="en_MZ", description="English locale for QA")
    qa_locale_french: Optional[str] = Field(default="fr_MZ", description="French locale for QA")
    qa_locale_portuguese: Optional[str] = Field(default="pt_MZ", description="Portuguese locale for QA")

    # Temp Environment
    temp_api_url: Optional[str] = Field(default=None, description="Temp environment API URL")
    temp_tenant_id: str = Field(default="mz", description="Tenant ID for Temp")
    temp_locale_english: Optional[str] = Field(default="en_MZ", description="English locale for Temp")
    temp_locale_french: Optional[str] = Field(default="fr_MZ", description="French locale for Temp")
    temp_locale_portuguese: Optional[str] = Field(default="pt_MZ", alias="temp_locale_portugueseh", description="Portuguese locale for Temp")

    def _get_env_config(self, env: str) -> dict:
        """Get all config for an environment as a dict."""
        env = env.lower()
        env_configs = {
            "uat": {
                "api_url": self.uat_api_url,
                "tenant_id": self.uat_tenant_id,
                "english": self.uat_locale_english,
                "french": self.uat_locale_french,
                "portuguese": self.uat_locale_portuguese,
            },
            "demo": {
                "api_url": self.demo_api_url,
                "tenant_id": self.demo_tenant_id,
                "english": self.demo_locale_english,
                "french": self.demo_locale_french,
                "portuguese": self.demo_locale_portuguese,
            },
            "qa": {
                "api_url": self.qa_api_url,
                "tenant_id": self.qa_tenant_id,
                "english": self.qa_locale_english,
                "french": self.qa_locale_french,
                "portuguese": self.qa_locale_portuguese,
            },
            "temp": {
                "api_url": self.temp_api_url,
                "tenant_id": self.temp_tenant_id,
                "english": self.temp_locale_english,
                "french": self.temp_locale_french,
                "portuguese": self.temp_locale_portuguese,
            },
        }
        if env not in env_configs:
            raise ValueError(f"Unknown environment: {env}. Must be one of: uat, demo, qa, temp")
        return env_configs[env]

    def get_api_url(self, env: str) -> str:
        """Get the API URL for a specific environment."""
        url = self._get_env_config(env)["api_url"]
        if not url:
            raise ValueError(f"No API URL configured for environment: {env}")
        return url

    def get_tenant_id(self, env: str) -> str:
        """Get the tenant ID for a specific environment."""
        return self._get_env_config(env)["tenant_id"]

    def get_auth_url(self, env: str) -> str:
        """Get the auth URL for a specific environment (derived from API URL)."""
        base_url = self.get_api_url(env)
        return f"{base_url.rstrip('/')}/user/oauth/token"

    @property
    def is_localhost(self) -> bool:
        """Check if upsert mode is localhost."""
        return self.upsert_mode.lower() == "localhost"

    def get_upsert_url(self, env: str) -> str:
        """Get the upsert base URL — localhost or remote based on upsert_mode."""
        if self.is_localhost:
            return f"http://localhost:{self.localhost_port}"
        return self.get_api_url(env)

    def get_locale(self, env: str, language: str) -> str:
        """
        Get the locale for a specific environment and language.

        Args:
            env: Environment name (uat, demo, qa, prod)
            language: Language code (en, fr, pt)

        Returns:
            Locale string (e.g., en_MZ, en_IN)
        """
        lang_map = {
            "en": "english",
            "english": "english",
            "fr": "french",
            "french": "french",
            "pt": "portuguese",
            "portuguese": "portuguese",
        }
        lang_key = lang_map.get(language.lower())
        if not lang_key:
            raise ValueError(f"Unknown language: {language}. Must be one of: en, fr, pt")

        config = self._get_env_config(env)
        locale = config.get(lang_key)
        if not locale:
            raise ValueError(f"No {lang_key} locale configured for environment: {env}")
        return locale


@lru_cache
def get_settings(env_file: Optional[str] = None) -> Settings:
    """Get cached settings instance."""
    if env_file:
        return Settings(_env_file=env_file)
    return Settings()
