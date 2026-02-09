"""CLI entry point for the localization sync framework."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from config import get_settings
from models import LocalizationMessage, SyncResult
from services import SyncService

app = typer.Typer(
    name="localization-sync",
    help="Sync localizations between environments",
    add_completion=False,
)
console = Console()


def setup_logging(verbose: bool = False) -> None:
    """Configure logging with rich handler."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, console=console)],
    )


def display_result(result: SyncResult) -> None:
    """Display sync result in a formatted table."""
    table = Table(title="Upsert Result")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green" if result.success else "red")

    table.add_row("Status", "Success" if result.success else "Failed")
    table.add_row("Target Environment", result.target_environment)
    table.add_row("Source Count", str(result.source_count))
    table.add_row("Created", str(result.total_created))
    table.add_row("Updated", str(result.total_updated))
    table.add_row("Failed", str(result.total_failed))
    table.add_row("Duration", f"{result.duration_seconds:.2f}s")

    if result.error:
        table.add_row("Error", result.error)

    console.print(table)


@app.command("upsert")
def upsert(
    lang: str = typer.Option(
        ...,
        "--lang",
        "-l",
        help="Language code (en, fr, pt)",
    ),
    module: Optional[str] = typer.Option(
        None,
        "--module",
        "-m",
        help="Module name filter",
    ),
    batch_size: int = typer.Option(
        100,
        "--batch-size",
        "-b",
        help="Number of items per batch",
    ),
    env_file: Optional[Path] = typer.Option(
        None,
        "--env-file",
        "-f",
        help="Path to environment file (e.g., .env.dev)",
    ),
    requests_dir: Path = typer.Option(
        Path("requests"),
        "--requests-dir",
        "-r",
        help="Directory containing request JSON files",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
) -> None:
    """Search localizations from SOURCE_ENV, transform locale, and upsert to TARGET_ENV."""
    setup_logging(verbose)

    try:
        env_file_str = str(env_file) if env_file else None
        settings = get_settings(env_file_str)
    except Exception as e:
        console.print(f"[red]Failed to load settings: {e}[/red]")
        raise typer.Exit(1)

    source_env = settings.source_env
    target_env = settings.target_env
    source_locale = settings.get_locale(source_env, lang)
    target_locale = settings.get_locale(target_env, lang)
    source_tenant = settings.get_tenant_id(source_env)
    target_tenant = settings.get_tenant_id(target_env)

    if settings.is_localhost:
        upsert_target = f"localhost:{settings.localhost_port}"
    else:
        upsert_target = target_env

    console.print(f"[cyan]Upserting localizations: {source_env} → {upsert_target}[/cyan]")
    console.print(f"[dim]Mode: {settings.upsert_mode.upper()} | Language: {lang.upper()}[/dim]")
    console.print(f"[dim]Source: tenant={source_tenant}, locale={source_locale}[/dim]")
    console.print(f"[dim]Target: tenant={target_tenant}, locale={target_locale}[/dim]")
    console.print(f"[dim]Module: {module or 'all'}[/dim]")

    output_dir = Path("output")
    service = SyncService(settings, requests_dir=requests_dir, output_dir=output_dir)
    result = asyncio.run(
        service.upsert(
            source_env=source_env,
            target_env=target_env,
            lang=lang,
            module=module,
            batch_size=batch_size,
            username=settings.auth_username,
            password=settings.auth_password,
        )
    )

    console.print(f"[dim]Output files saved to: {output_dir.absolute()}[/dim]")

    display_result(result)

    if not result.success:
        raise typer.Exit(1)


@app.command("search")
def search(
    lang: str = typer.Option(
        ...,
        "--lang",
        "-l",
        help="Language code (en, fr, pt)",
    ),
    module: Optional[str] = typer.Option(
        None,
        "--module",
        "-m",
        help="Module name filter",
    ),
    env_file: Optional[Path] = typer.Option(
        None,
        "--env-file",
        "-f",
        help="Path to environment file",
    ),
    requests_dir: Path = typer.Option(
        Path("requests"),
        "--requests-dir",
        "-r",
        help="Directory containing request JSON files",
    ),
    output_dir: Path = typer.Option(
        Path("output"),
        "--output-dir",
        "-o",
        help="Directory to save output files",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
) -> None:
    """Fetch localizations from SOURCE_ENV and save response. Also saves upsert body for TARGET_ENV."""
    setup_logging(verbose)

    try:
        env_file_str = str(env_file) if env_file else None
        settings = get_settings(env_file_str)
    except Exception as e:
        console.print(f"[red]Failed to load settings: {e}[/red]")
        raise typer.Exit(1)

    source_env = settings.source_env
    target_env = settings.target_env
    source_locale = settings.get_locale(source_env, lang)
    target_locale = settings.get_locale(target_env, lang)

    console.print(f"[cyan]Fetching localizations from {source_env}...[/cyan]")
    console.print(f"[dim]Language: {lang.upper()}, Locale: {source_locale}[/dim]")
    console.print(f"[dim]Module: {module or 'all'}[/dim]")
    if target_locale != source_locale:
        console.print(f"[dim]Will also save upsert body for {target_env} (locale: {target_locale})[/dim]")

    service = SyncService(settings, requests_dir=requests_dir, output_dir=output_dir)

    async def do_fetch():
        return await service.fetch_and_save(
            source_env=source_env,
            lang=lang,
            module=module,
            target_env=target_env,
        )

    try:
        messages, search_file, upsert_file = asyncio.run(do_fetch())

        table = Table(title="Search Result")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Total Messages", str(len(messages)))
        table.add_row("Search Response Saved", str(search_file))
        if upsert_file:
            table.add_row("Upsert Body Saved", str(upsert_file))

        console.print(table)
        console.print(f"[green]Search completed. Files saved to: {output_dir.absolute()}[/green]")

    except Exception as e:
        console.print(f"[red]Search failed: {e}[/red]")
        raise typer.Exit(1)


@app.command("upsert-file")
def upsert_from_file(
    input_file: Path = typer.Option(
        ...,
        "--input",
        "-i",
        help="JSON file containing messages to upsert",
    ),
    batch_size: int = typer.Option(
        100,
        "--batch-size",
        "-b",
        help="Number of items per batch",
    ),
    env_file: Optional[Path] = typer.Option(
        None,
        "--env-file",
        "-f",
        help="Path to environment file",
    ),
    requests_dir: Path = typer.Option(
        Path("requests"),
        "--requests-dir",
        "-r",
        help="Directory containing request JSON files",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
) -> None:
    """Upsert localizations from a JSON file to TARGET_ENV."""
    setup_logging(verbose)

    if not input_file.exists():
        console.print(f"[red]Input file not found: {input_file}[/red]")
        raise typer.Exit(1)

    try:
        env_file_str = str(env_file) if env_file else None
        settings = get_settings(env_file_str)
    except Exception as e:
        console.print(f"[red]Failed to load settings: {e}[/red]")
        raise typer.Exit(1)

    target_env = settings.target_env

    # Load messages from input file
    with open(input_file) as f:
        data = json.load(f)

    tenant_id = data.get("tenantId")
    module = data.get("module")
    locale = data.get("locale")
    messages_data = data.get("messages", [])

    if not all([tenant_id, module, locale, messages_data]):
        console.print("[red]Input file must contain tenantId, module, locale, and messages[/red]")
        raise typer.Exit(1)

    messages = [LocalizationMessage(**msg) for msg in messages_data]
    if settings.is_localhost:
        upsert_target = f"localhost:{settings.localhost_port}"
    else:
        upsert_target = target_env

    console.print(f"[cyan]Upserting {len(messages)} messages to {upsert_target}...[/cyan]")
    console.print(f"[dim]Mode: {settings.upsert_mode.upper()} | Tenant: {tenant_id}, Module: {module}, Locale: {locale}[/dim]")

    service = SyncService(settings, requests_dir=requests_dir)
    result = asyncio.run(
        service.upsert_messages(
            target_env=target_env,
            messages=messages,
            tenant_id=tenant_id,
            module=module,
            locale=locale,
            batch_size=batch_size,
            username=settings.auth_username,
            password=settings.auth_password,
        )
    )

    display_result(result)

    if not result.success:
        raise typer.Exit(1)


@app.command("login")
def login(
    username: str = typer.Option(
        ...,
        "--username",
        "-u",
        help="Username",
    ),
    password: str = typer.Option(
        ...,
        "--password",
        "-p",
        prompt=True,
        hide_input=True,
        help="Password",
    ),
    env: Optional[str] = typer.Option(
        None,
        "--env",
        "-e",
        help="Environment to authenticate against (defaults to TARGET_ENV from config)",
    ),
    env_file: Optional[Path] = typer.Option(
        None,
        "--env-file",
        "-f",
        help="Path to environment file",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
) -> None:
    """Authenticate and display access token."""
    setup_logging(verbose)

    try:
        env_file_str = str(env_file) if env_file else None
        settings = get_settings(env_file_str)
    except Exception as e:
        console.print(f"[red]Failed to load settings: {e}[/red]")
        raise typer.Exit(1)

    target = env or settings.target_env
    tenant_id = settings.get_tenant_id(target)
    auth_url = settings.get_auth_url(target)
    console.print(f"[cyan]Authenticating user {username} against {target}...[/cyan]")
    console.print(f"[dim]Auth URL: {auth_url}, Tenant: {tenant_id}[/dim]")

    from clients import AuthClient

    async def do_login():
        auth_client = AuthClient(
            auth_url=auth_url,
            client_credentials=settings.auth_client_credentials,
        )
        return await auth_client.get_token(
            username=username,
            password=password,
            tenant_id=tenant_id,
        )

    try:
        auth_response = asyncio.run(do_login())

        table = Table(title="Authentication Result")
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Status", "Success")
        table.add_row("Token Type", auth_response.token_type)
        table.add_row("Access Token", auth_response.access_token[:50] + "..." if auth_response.access_token else "N/A")
        table.add_row("Expires In", f"{auth_response.expires_in}s" if auth_response.expires_in else "N/A")

        console.print(table)

        # Print full token for copying
        console.print("\n[dim]Full access token:[/dim]")
        console.print(f"[green]{auth_response.access_token}[/green]")

    except Exception as e:
        console.print(f"[red]Authentication failed: {e}[/red]")
        raise typer.Exit(1)


@app.command("validate")
def validate(
    env_file: Optional[Path] = typer.Option(
        None,
        "--env-file",
        "-f",
        help="Path to environment file to validate",
    ),
    requests_dir: Path = typer.Option(
        Path("requests"),
        "--requests-dir",
        "-r",
        help="Directory containing request JSON files",
    ),
) -> None:
    """Validate the configuration and request files."""
    try:
        env_file_str = str(env_file) if env_file else None
        settings = get_settings(env_file_str)

        table = Table(title="Configuration")
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Source Environment", settings.source_env)
        table.add_row("Target Environment", settings.target_env)

        for env_name in ["uat", "demo", "qa", "temp"]:
            try:
                url = settings.get_api_url(env_name)
                tenant = settings.get_tenant_id(env_name)
                table.add_row(f"{env_name.upper()} API URL", url or "Not set")
                table.add_row(f"{env_name.upper()} Tenant", tenant)
            except ValueError:
                table.add_row(f"{env_name.upper()}", "Not configured")

        console.print(table)

        # Validate request files
        request_table = Table(title="Request Files")
        request_table.add_column("File", style="cyan")
        request_table.add_column("Status", style="green")

        for json_file in ["auth.json", "search.json", "upsert.json"]:
            file_path = requests_dir / json_file
            if file_path.exists():
                try:
                    with open(file_path) as f:
                        json.load(f)
                    request_table.add_row(json_file, "Valid")
                except json.JSONDecodeError as e:
                    request_table.add_row(json_file, f"[red]Invalid JSON: {e}[/red]")
            else:
                request_table.add_row(json_file, "[yellow]Not found[/yellow]")

        console.print(request_table)
        console.print("[green]Configuration is valid![/green]")

    except Exception as e:
        console.print(f"[red]Configuration error: {e}[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
