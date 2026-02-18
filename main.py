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
        help="Module name(s), comma-separated (e.g. digit-ui,hcm-common)",
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

    modules = [m.strip() for m in module.split(",")] if module else [None]

    console.print(f"[cyan]Upserting localizations: {source_env} → {upsert_target}[/cyan]")
    console.print(f"[dim]Mode: {settings.upsert_mode.upper()} | Language: {lang.upper()}[/dim]")
    console.print(f"[dim]Source: tenant={source_tenant}, locale={source_locale}[/dim]")
    console.print(f"[dim]Target: tenant={target_tenant}, locale={target_locale}[/dim]")
    console.print(f"[dim]Modules: {', '.join(m for m in modules if m) or 'all'}[/dim]")

    output_dir = Path("output")
    service = SyncService(settings, requests_dir=requests_dir, output_dir=output_dir)
    has_failure = False

    for mod in modules:
        if len(modules) > 1:
            console.print(f"\n[bold cyan]--- Module: {mod} ---[/bold cyan]")

        result = asyncio.run(
            service.upsert(
                source_env=source_env,
                target_env=target_env,
                lang=lang,
                module=mod,
                batch_size=batch_size,
                username=settings.auth_username,
                password=settings.auth_password,
            )
        )

        display_result(result)
        if not result.success:
            has_failure = True

    console.print(f"\n[dim]Output files saved to: {output_dir.absolute()}[/dim]")

    if has_failure:
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
        help="Module name(s), comma-separated (e.g. digit-ui,hcm-common)",
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

    modules = [m.strip() for m in module.split(",")] if module else [None]

    console.print(f"[cyan]Fetching localizations from {source_env}...[/cyan]")
    console.print(f"[dim]Language: {lang.upper()}, Locale: {source_locale}[/dim]")
    console.print(f"[dim]Modules: {', '.join(m for m in modules if m) or 'all'}[/dim]")
    if target_locale != source_locale:
        console.print(f"[dim]Will also save upsert body for {target_env} (locale: {target_locale})[/dim]")

    service = SyncService(settings, requests_dir=requests_dir, output_dir=output_dir)
    has_failure = False

    for mod in modules:
        if len(modules) > 1:
            console.print(f"\n[bold cyan]--- Module: {mod} ---[/bold cyan]")

        try:
            messages, search_file, upsert_file = asyncio.run(
                service.fetch_and_save(
                    source_env=source_env,
                    lang=lang,
                    module=mod,
                    target_env=target_env,
                )
            )

            table = Table(title=f"Search Result{f' — {mod}' if mod else ''}")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", style="green")

            table.add_row("Total Messages", str(len(messages)))
            table.add_row("Search Response Saved", str(search_file))
            if upsert_file:
                table.add_row("Upsert Body Saved", str(upsert_file))

            console.print(table)

        except Exception as e:
            console.print(f"[red]Search failed for {mod or 'all'}: {e}[/red]")
            has_failure = True

    console.print(f"\n[green]Files saved to: {output_dir.absolute()}[/green]")

    if has_failure:
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

        for env_name in ["dev", "qa", "uat", "demo", "temp"]:
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


@app.command("batch")
def batch(
    commands_file: Path = typer.Option(
        Path("commands.txt"),
        "--file",
        "-f",
        help="Path to commands file listing upsert commands to execute",
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
    """Execute all upsert commands from a commands file sequentially."""
    setup_logging(verbose)

    if not commands_file.exists():
        console.print(f"[red]Commands file not found: {commands_file}[/red]")
        raise typer.Exit(1)

    try:
        env_file_str = str(env_file) if env_file else None
        settings = get_settings(env_file_str)
    except Exception as e:
        console.print(f"[red]Failed to load settings: {e}[/red]")
        raise typer.Exit(1)

    # Parse commands from file
    commands: list[dict[str, str]] = []
    with open(commands_file) as f:
        for line in f:
            line = line.strip()
            # Skip empty lines, comments (#), and separator lines (underscores)
            if not line or line.startswith("#") or line.startswith("_"):
                continue
            # Skip section headers (lines without "python" or "--")
            if "main.py" not in line and "--" not in line:
                continue

            # Extract --lang and --module from the command
            parts = line.split()
            lang_val = None
            module_val = None
            for i, part in enumerate(parts):
                if part in ("--lang", "-l") and i + 1 < len(parts):
                    lang_val = parts[i + 1]
                elif part in ("--module", "-m") and i + 1 < len(parts):
                    module_val = parts[i + 1]

            if lang_val:
                commands.append({"lang": lang_val, "module": module_val or ""})

    if not commands:
        console.print("[yellow]No commands found in file[/yellow]")
        raise typer.Exit(0)

    console.print(f"[cyan]Found {len(commands)} commands in {commands_file}[/cyan]")
    console.print(f"[dim]Source: {settings.source_env} -> Target: {settings.target_env}[/dim]")
    console.print()

    source_env = settings.source_env
    target_env = settings.target_env
    output_dir = Path("output")
    service = SyncService(settings, requests_dir=requests_dir, output_dir=output_dir)

    total = len(commands)
    passed = 0
    failed = 0

    for idx, cmd in enumerate(commands, 1):
        lang = cmd["lang"]
        module_str = cmd["module"]
        modules = [m.strip() for m in module_str.split(",")] if module_str else [None]
        module_label = module_str or "all"

        console.print(f"[bold cyan]━━━ [{idx}/{total}] lang={lang} module={module_label} ━━━[/bold cyan]")

        cmd_failed = False
        for mod in modules:
            if len(modules) > 1:
                console.print(f"  [dim]Module: {mod}[/dim]")

            result = asyncio.run(
                service.upsert(
                    source_env=source_env,
                    target_env=target_env,
                    lang=lang,
                    module=mod,
                    batch_size=batch_size,
                    username=settings.auth_username,
                    password=settings.auth_password,
                )
            )

            display_result(result)
            if not result.success:
                cmd_failed = True

        if cmd_failed:
            failed += 1
        else:
            passed += 1

    # Summary
    console.print()
    summary = Table(title="Batch Summary")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green" if failed == 0 else "yellow")
    summary.add_row("Total Commands", str(total))
    summary.add_row("Passed", str(passed))
    summary.add_row("Failed", str(failed))
    console.print(summary)

    # Regenerate the Postman collection after batch completes
    console.print("\n[cyan]Updating Postman collection...[/cyan]")
    try:
        postman_output = Path("Localization_Framework.postman_collection.json")
        _build_postman_collection(settings, commands_file, requests_dir, postman_output)
    except Exception as e:
        console.print(f"[yellow]Warning: Failed to update Postman collection: {e}[/yellow]")

    if failed > 0:
        raise typer.Exit(1)


def _parse_commands_file(commands_file: Path) -> dict[str, list[str]]:
    """Parse commands.txt to extract {lang: [modules]} mapping."""
    lang_modules: dict[str, list[str]] = {}
    with open(commands_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("_"):
                continue
            if "main.py" not in line and "--" not in line:
                continue

            parts = line.split()
            lang_val = None
            module_val = None
            for i, part in enumerate(parts):
                if part in ("--lang", "-l") and i + 1 < len(parts):
                    lang_val = parts[i + 1]
                elif part in ("--module", "-m") and i + 1 < len(parts):
                    module_val = parts[i + 1]

            if lang_val and module_val:
                if lang_val not in lang_modules:
                    lang_modules[lang_val] = []
                for m in module_val.split(","):
                    m = m.strip()
                    if m and m not in lang_modules[lang_val]:
                        lang_modules[lang_val].append(m)
    return lang_modules


def _build_postman_collection(
    settings,
    commands_file: Path,
    requests_dir: Path,
    output: Path,
) -> None:
    """Authenticate, fetch messages, and write the Postman collection JSON."""
    from config import Settings

    LANG_CONFIG = {
        "en": {"name": "English", "locale_var": "{{localeEnglish}}"},
        "fr": {"name": "French", "locale_var": "{{localeFrench}}"},
        "pt": {"name": "Portuguese", "locale_var": "{{localePortuguese}}"},
    }

    lang_modules = _parse_commands_file(commands_file)
    if not lang_modules:
        console.print("[yellow]No modules found in commands file — skipping Postman generation[/yellow]")
        return

    for lang, modules in lang_modules.items():
        console.print(f"[dim]{LANG_CONFIG.get(lang, {}).get('name', lang)}: {len(modules)} modules[/dim]")

    # Authenticate against the source environment
    source_env = settings.source_env
    console.print(f"[cyan]Authenticating against {source_env} for Postman collection...[/cyan]")

    service = SyncService(settings, requests_dir=requests_dir)
    asyncio.run(service.authenticate(env=source_env))
    console.print("[green]Authentication successful[/green]")

    # Fetch messages for each language + module
    search_request_info = service._load_request_info("search.json")
    if service._auth_token and search_request_info:
        search_request_info.authToken = service._auth_token

    source_url = settings.get_api_url(source_env)
    source_tenant = settings.get_tenant_id(source_env)

    all_messages: dict[str, dict[str, list]] = {}

    for lang, modules in lang_modules.items():
        source_locale = settings.get_locale(source_env, lang)
        all_messages[lang] = {}

        for mod in modules:
            console.print(f"[dim]Fetching {lang}/{mod}...[/dim]")
            try:
                messages = asyncio.run(
                    _fetch_messages(source_url, search_request_info, source_locale, mod, source_tenant)
                )
                all_messages[lang][mod] = [
                    {"code": msg.code, "message": msg.message, "module": msg.module, "locale": msg.locale}
                    for msg in messages
                ]
                console.print(f"[dim]  → {len(messages)} messages[/dim]")
            except Exception as e:
                console.print(f"[yellow]  Warning: Failed to fetch {lang}/{mod}: {e}[/yellow]")
                all_messages[lang][mod] = []

    # Build the Postman collection
    console.print("[cyan]Building Postman collection...[/cyan]")

    auth_folder = {
        "name": "Auth",
        "item": [
            {
                "name": "Login",
                "event": [
                    {
                        "listen": "test",
                        "script": {
                            "type": "text/javascript",
                            "exec": [
                                "var jsonData = pm.response.json();",
                                "if (jsonData.access_token) {",
                                "    pm.collectionVariables.set(\"auth_token\", jsonData.access_token);",
                                "    console.log(\"Auth token saved successfully\");",
                                "}",
                            ],
                        },
                    }
                ],
                "request": {
                    "method": "POST",
                    "header": [
                        {"key": "Authorization", "value": "Basic "},
                        {"key": "Content-Type", "value": "application/x-www-form-urlencoded"},
                        {"key": "Accept", "value": "application/json, text/plain, */*"},
                    ],
                    "body": {
                        "mode": "urlencoded",
                        "urlencoded": [
                            {"key": "username", "value": "{{username}}", "type": "text"},
                            {"key": "password", "value": "{{password}}", "type": "text"},
                            {"key": "grant_type", "value": "password", "type": "text"},
                            {"key": "scope", "value": "read", "type": "text"},
                            {"key": "tenantId", "value": "{{tenant_id}}", "type": "text"},
                            {"key": "userType", "value": "EMPLOYEE", "type": "text"},
                        ],
                    },
                    "url": {
                        "raw": "{{URL}}/user/oauth/token",
                        "host": ["{{URL}}"],
                        "path": ["user", "oauth", "token"],
                    },
                },
                "response": [],
            }
        ],
    }

    language_folders = []
    for lang, modules in lang_modules.items():
        cfg = LANG_CONFIG.get(lang)
        if not cfg:
            console.print(f"[yellow]Skipping unknown language: {lang}[/yellow]")
            continue

        folder_name = cfg["name"]
        locale_var = cfg["locale_var"]
        folder_items = []

        for mod in modules:
            messages = all_messages.get(lang, {}).get(mod, [])
            postman_messages = [
                {"code": msg["code"], "message": msg["message"], "module": mod, "locale": locale_var}
                for msg in messages
            ]

            request_body = {
                "RequestInfo": {
                    "apiId": "Rainmaker",
                    "ver": ".01",
                    "ts": "",
                    "action": "_search",
                    "did": "1",
                    "key": "",
                    "msgId": "20170310130900|en_IN",
                    "authToken": "{{auth_token}}",
                    "userInfo": None,
                },
                "tenantId": "mz",
                "module": mod,
                "locale": locale_var,
                "messages": postman_messages,
            }

            raw_body = json.dumps(request_body, indent=4, ensure_ascii=False)

            folder_items.append(
                {
                    "name": mod,
                    "request": {
                        "method": "POST",
                        "header": [
                            {"key": "Content-Type", "value": "application/json"},
                            {"key": "Accept", "value": "application/json"},
                        ],
                        "body": {
                            "mode": "raw",
                            "raw": raw_body,
                            "options": {"raw": {"language": "json"}},
                        },
                        "url": {
                            "raw": "{{URL}}/localization/messages/v1/_upsert?tenantId={{tenant_id}}",
                            "host": ["{{URL}}"],
                            "path": ["localization", "messages", "v1", "_upsert"],
                            "query": [{"key": "tenantId", "value": "{{tenant_id}}"}],
                        },
                    },
                    "response": [],
                }
            )

        language_folders.append({"name": folder_name, "item": folder_items})

    collection = {
        "info": {
            "_postman_id": "b9824023-3a7f-4ca2-9fb2-2e35b7ce2ca5",
            "name": "Localization_Seed_Script",
            "description": (
                "API collection for searching and upserting localizations across environments.\n\n"
                "Setup:\n"
                "1. Run the Login request first to auto-save the auth token\n"
                "2. Update collection variables (URL, tenant_id, locales) for your target environment\n"
                "3. Use language folders to search localizations per module"
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": [auth_folder] + language_folders,
        "variable": [
            {"key": "URL", "value": settings.get_api_url(source_env), "type": "string"},
            {"key": "tenant_id", "value": "mz", "type": "string"},
            {"key": "username", "value": "", "type": "string"},
            {"key": "password", "value": "", "type": "string"},
            {"key": "auth_token", "value": "", "type": "string"},
            {"key": "localeEnglish", "value": "en_MZ", "type": "string"},
            {"key": "localeFrench", "value": "fr_MZ", "type": "string"},
            {"key": "localePortuguese", "value": "pt_MZ", "type": "string"},
        ],
    }

    with open(output, "w") as f:
        json.dump(collection, f, indent=2, ensure_ascii=False)

    # Print summary
    console.print()
    table = Table(title="Postman Collection Generated")
    table.add_column("Language", style="cyan")
    table.add_column("Modules", style="green")
    table.add_column("Total Messages", style="green")

    for lang, modules in lang_modules.items():
        cfg = LANG_CONFIG.get(lang, {})
        total_msgs = sum(len(all_messages.get(lang, {}).get(mod, [])) for mod in modules)
        table.add_row(cfg.get("name", lang), str(len(modules)), str(total_msgs))

    console.print(table)
    console.print(f"\n[green]Collection saved to: {output.absolute()}[/green]")


@app.command("generate-postman")
def generate_postman(
    commands_file: Path = typer.Option(
        Path("commands.txt"),
        "--file",
        "-f",
        help="Path to commands file listing modules per language",
    ),
    env_file: Optional[Path] = typer.Option(
        None,
        "--env-file",
        help="Path to environment file",
    ),
    requests_dir: Path = typer.Option(
        Path("requests"),
        "--requests-dir",
        "-r",
        help="Directory containing request JSON files",
    ),
    output: Path = typer.Option(
        Path("Localization_Framework.postman_collection.json"),
        "--output",
        "-o",
        help="Output path for the Postman collection JSON",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
) -> None:
    """Generate a Postman collection from commands.txt by fetching messages from the source environment."""
    setup_logging(verbose)

    if not commands_file.exists():
        console.print(f"[red]Commands file not found: {commands_file}[/red]")
        raise typer.Exit(1)

    try:
        env_file_str = str(env_file) if env_file else None
        settings = get_settings(env_file_str)
    except Exception as e:
        console.print(f"[red]Failed to load settings: {e}[/red]")
        raise typer.Exit(1)

    try:
        _build_postman_collection(settings, commands_file, requests_dir, output)
    except Exception as e:
        console.print(f"[red]Failed to generate Postman collection: {e}[/red]")
        raise typer.Exit(1)


async def _fetch_messages(source_url, request_info, locale, module, tenant_id):
    """Helper to fetch messages for a single module using SearchClient."""
    from clients import SearchClient

    async with SearchClient(base_url=source_url, request_info=request_info) as client:
        return await client.search(locale=locale, module=module, tenant_id=tenant_id)


if __name__ == "__main__":
    app()
