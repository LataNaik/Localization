"""Upsert localizations to localhost. Auth via remote TARGET_ENV.

Usage:
    python3 localhost_upsert.py digit-ui
    python3 localhost_upsert.py digit-ui --lang fr
    python3 localhost_upsert.py digit-ui --port 8080
    python3 localhost_upsert.py --file output/20260209_upsert_body_uat_en_IN.json
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from clients import AuthClient, SearchClient, UpsertClient
from config import get_settings
from models import LocalizationMessage, RequestInfo, SyncResult, UserInfo

console = Console()


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, console=console)],
    )


def display_result(result: SyncResult) -> None:
    table = Table(title="Localhost Upsert Result")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green" if result.success else "red")

    table.add_row("Status", "Success" if result.success else "Failed")
    table.add_row("Target", result.target_environment)
    table.add_row("Source Count", str(result.source_count))
    table.add_row("Created", str(result.total_created))
    table.add_row("Updated", str(result.total_updated))
    table.add_row("Failed", str(result.total_failed))
    table.add_row("Duration", f"{result.duration_seconds:.2f}s")

    if result.error:
        table.add_row("Error", result.error)

    console.print(table)


def _load_request_info(requests_dir: Path, json_file: str) -> Optional[RequestInfo]:
    file_path = requests_dir / json_file
    if not file_path.exists():
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
        action=ri_data.get("action", "_create"),
        did=ri_data.get("did", "1"),
        key=ri_data.get("key", ""),
        msgId=ri_data.get("msgId", ""),
        authToken=ri_data.get("authToken"),
        userInfo=user_info,
    )


async def _authenticate(settings, target_env: str) -> str:
    tenant_id = settings.get_tenant_id(target_env)
    auth_url = settings.get_auth_url(target_env)

    console.print(f"[cyan]Authenticating against {target_env}: {auth_url}[/cyan]")

    auth_client = AuthClient(
        auth_url=auth_url,
        client_credentials=settings.auth_client_credentials,
    )
    auth_response = await auth_client.get_token(
        username=settings.auth_username,
        password=settings.auth_password,
        tenant_id=tenant_id,
    )

    console.print("[green]Authentication successful[/green]")
    return auth_response.access_token


def main(
    module: str = typer.Argument(
        None, help="Module name to search and upsert (e.g. digit-ui)"
    ),
    lang: str = typer.Option(
        "en", "--lang", "-l", help="Language code (en, fr, pt)"
    ),
    port: int = typer.Option(
        8765, "--port", "-p", help="Localhost port"
    ),
    host: str = typer.Option(
        "localhost", "--host", "-H", help="Localhost hostname"
    ),
    file: Optional[Path] = typer.Option(
        None, "--file", "-f", help="Upsert from a saved JSON file instead of searching"
    ),
    batch_size: int = typer.Option(
        100, "--batch-size", "-b", help="Number of items per batch"
    ),
    env_file: Optional[Path] = typer.Option(
        None, "--env-file", help="Path to environment file"
    ),
    requests_dir: Path = typer.Option(
        Path("requests"), "--requests-dir", help="Directory containing request JSON files"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable verbose logging"
    ),
) -> None:
    """Search localizations by module from SOURCE_ENV and upsert to localhost."""
    setup_logging(verbose)
    logger = logging.getLogger(__name__)

    # Validate: need either module or --file
    if not module and not file:
        console.print("[red]Provide a module name or use --file[/red]")
        console.print("[dim]  python3 localhost_upsert.py digit-ui[/dim]")
        console.print("[dim]  python3 localhost_upsert.py --file output/some_file.json[/dim]")
        raise typer.Exit(1)

    try:
        env_file_str = str(env_file) if env_file else None
        settings = get_settings(env_file_str)
    except Exception as e:
        console.print(f"[red]Failed to load settings: {e}[/red]")
        raise typer.Exit(1)

    localhost_url = f"http://{host}:{port}"
    target_env = settings.target_env

    # --- Mode 1: Upsert from file ---
    if file:
        if not file.exists():
            console.print(f"[red]File not found: {file}[/red]")
            raise typer.Exit(1)

        with open(file) as fh:
            data = json.load(fh)

        tenant_id = data.get("tenantId")
        file_module = data.get("module")
        locale = data.get("locale")
        messages_data = data.get("messages", [])

        if not all([tenant_id, file_module, locale, messages_data]):
            console.print("[red]File must contain tenantId, module, locale, and messages[/red]")
            raise typer.Exit(1)

        messages = [LocalizationMessage(**msg) for msg in messages_data]

        console.print(f"[cyan]Upserting {len(messages)} messages to {localhost_url}[/cyan]")
        console.print(f"[dim]Auth via: {target_env} | Tenant: {tenant_id} | Module: {file_module} | Locale: {locale}[/dim]")

        async def do_file_upsert():
            start_time = time.time()
            try:
                token = await _authenticate(settings, target_env)
                request_info = _load_request_info(requests_dir, "upsert.json")
                if request_info:
                    request_info.authToken = token

                async with UpsertClient(
                    base_url=localhost_url,
                    request_info=request_info,
                ) as upsert_client:
                    upsert_results = await upsert_client.upsert_batch(
                        messages=messages,
                        tenant_id=tenant_id,
                        module=file_module,
                        locale=locale,
                        batch_size=batch_size,
                    )

                total_created = sum(r.created for r in upsert_results)
                total_updated = sum(r.updated for r in upsert_results)
                total_failed = sum(r.failed for r in upsert_results)
                all_success = all(r.success for r in upsert_results)

                return SyncResult(
                    success=all_success,
                    source_count=len(messages),
                    target_environment=f"localhost:{port}",
                    upsert_results=upsert_results,
                    total_created=total_created,
                    total_updated=total_updated,
                    total_failed=total_failed,
                    duration_seconds=time.time() - start_time,
                )
            except Exception as e:
                logger.exception(f"Upsert failed: {e}")
                return SyncResult(
                    success=False,
                    source_count=len(messages),
                    target_environment=f"localhost:{port}",
                    duration_seconds=time.time() - start_time,
                    error=str(e),
                )

        result = asyncio.run(do_file_upsert())
        display_result(result)
        if not result.success:
            raise typer.Exit(1)
        return

    # --- Mode 2: Search by module + upsert to localhost ---
    source_env = settings.source_env
    source_locale = settings.get_locale(source_env, lang)
    target_locale = settings.get_locale(target_env, lang)
    source_tenant = settings.get_tenant_id(source_env)
    target_tenant = settings.get_tenant_id(target_env)

    console.print(f"[cyan]Search: {source_env} → Upsert: {localhost_url}[/cyan]")
    console.print(f"[dim]Auth via: {target_env} | Lang: {lang.upper()} | Module: {module}[/dim]")
    console.print(f"[dim]Source: tenant={source_tenant}, locale={source_locale}[/dim]")
    console.print(f"[dim]Target: tenant={target_tenant}, locale={target_locale}[/dim]")

    async def do_upsert():
        start_time = time.time()
        try:
            token = await _authenticate(settings, target_env)

            search_request_info = _load_request_info(requests_dir, "search.json")
            upsert_request_info = _load_request_info(requests_dir, "upsert.json")

            if search_request_info:
                search_request_info.authToken = token
            if upsert_request_info:
                upsert_request_info.authToken = token

            # Search from source environment (remote)
            source_url = settings.get_api_url(source_env)
            async with SearchClient(
                base_url=source_url,
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
                    target_environment=f"localhost:{port}",
                    duration_seconds=time.time() - start_time,
                )

            # Save raw search response
            output_dir = Path("output")
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            search_file = output_dir / f"{timestamp}_search_response_{source_env}_{source_locale}.json"
            with open(search_file, "w") as f:
                json.dump(
                    {
                        "messages": [msg.model_dump() for msg in messages],
                        "tenantId": source_tenant,
                        "locale": source_locale,
                        "module": module,
                        "sourceEnv": source_env,
                        "totalCount": source_count,
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
            logger.info(f"Saved search response to {search_file}")

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

            # Save upsert body
            upsert_module = module or messages[0].module
            upsert_file = output_dir / f"{timestamp}_upsert_body_localhost_{target_locale}.json"
            with open(upsert_file, "w") as f:
                json.dump(
                    {
                        "tenantId": target_tenant,
                        "module": upsert_module,
                        "locale": target_locale,
                        "messages": [msg.model_dump() for msg in messages],
                        "targetEnv": f"localhost:{port}",
                        "totalCount": len(messages),
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
            logger.info(f"Saved upsert body to {upsert_file}")

            # Upsert to localhost
            async with UpsertClient(
                base_url=localhost_url,
                request_info=upsert_request_info,
            ) as upsert_client:
                upsert_results = await upsert_client.upsert_batch(
                    messages=messages,
                    tenant_id=target_tenant,
                    module=upsert_module,
                    locale=target_locale,
                    batch_size=batch_size,
                )

            total_created = sum(r.created for r in upsert_results)
            total_updated = sum(r.updated for r in upsert_results)
            total_failed = sum(r.failed for r in upsert_results)
            all_success = all(r.success for r in upsert_results)

            return SyncResult(
                success=all_success,
                source_count=source_count,
                target_environment=f"localhost:{port}",
                upsert_results=upsert_results,
                total_created=total_created,
                total_updated=total_updated,
                total_failed=total_failed,
                duration_seconds=time.time() - start_time,
            )

        except Exception as e:
            logger.exception(f"Upsert failed: {e}")
            return SyncResult(
                success=False,
                source_count=0,
                target_environment=f"localhost:{port}",
                duration_seconds=time.time() - start_time,
                error=str(e),
            )

    result = asyncio.run(do_upsert())
    console.print(f"[dim]Output files saved to: {Path('output').absolute()}[/dim]")
    display_result(result)

    if not result.success:
        raise typer.Exit(1)


if __name__ == "__main__":
    typer.run(main)
