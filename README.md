# Localization Sync Framework

CLI tool to search localizations from one environment and upsert them to another (or to localhost).

## Setup

```bash
cd localization_framework
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
cp .env.example .env
```

## Execution

```bash
cd localization_framework
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
python3 main.py upsert --lang en --module digit-ui
```

## Configuration

Edit `.env`:

```env
# Environments
SOURCE_ENV=demo
TARGET_ENV=prod

# Upsert mode: "auth" (remote TARGET_ENV) or "localhost"
UPSERT_MODE=auth
LOCALHOST_PORT=8082

# Auth credentials
AUTH_USERNAME=LNMZ
AUTH_PASSWORD=eGov@1234
```

### Upsert Mode

| Mode | Upsert target | Auth | Search |
|---|---|---|---|
| `auth` | Remote `TARGET_ENV` URL | Remote `TARGET_ENV` | Remote `SOURCE_ENV` |
| `localhost` | `http://localhost:{LOCALHOST_PORT}` | Remote `TARGET_ENV` | Remote `SOURCE_ENV` |

Auth and search always use remote environment URLs regardless of upsert mode.

### Per-Environment Config

Each environment (UAT, DEMO, QA, PROD) has:

| Variable | Example |
|---|---|
| `{ENV}_API_URL` | `https://unified-uat.digit.org` |
| `{ENV}_TENANT_ID` | `mz` |
| `{ENV}_LOCALE_ENGLISH` | `en_IN` |
| `{ENV}_LOCALE_FRENCH` | `fr_IN` |
| `{ENV}_LOCALE_PORTUGUESEH` | `pt_IN` |

## Commands

### Upsert

Search from `SOURCE_ENV`, transform locale, upsert to target (remote or localhost based on `UPSERT_MODE`).

```bash
python3 main.py upsert --lang en --module digit-ui
python3 main.py upsert --lang fr --module hcm-common
python3 main.py upsert --lang en --batch-size 50
```

### Search only

Fetch and save to `output/` without upserting.

```bash
python3 main.py search --lang en
python3 main.py search --lang en --module digit-ui
```

### Upsert from file

Upsert from a previously saved JSON file.

```bash
python3 main.py upsert-file --input output/20260209_upsert_body_uat_en_IN.json
```

### Login

Test authentication.

```bash
python3 main.py login --username LNMZ
```

### Batch

Execute all upsert commands from a commands file sequentially. Reads `commands.txt` (or a custom file), parses `--lang` and `--module` from each line, and runs them one by one.

```bash
# Run all commands from the default commands.txt
python3 main.py batch

# Use a custom commands file
python3 main.py batch --file my_commands.txt

# With options
python3 main.py batch --batch-size 50 --verbose
```

The commands file supports:
- Lines starting with `python3 main.py upsert --lang ... --module ...`
- `#` comments
- Section headers (e.g., `English`, `French`) are skipped automatically
- Blank lines and `___` separator lines are skipped

Example `commands.txt`:

```
# English
python3 main.py upsert --lang en --module hcm-login,hcm-common,hcm-scanner
python3 main.py upsert --lang en --module hcm-campaignmanager,digit-ui

# French
python3 main.py upsert --lang fr --module hcm-login,hcm-common,hcm-scanner
python3 main.py upsert --lang fr --module hcm-campaignmanager,digit-ui
```

### Validate

Check configuration and request files.

```bash
python3 main.py validate
```

## Project Structure

```
localization_framework/
├── main.py              # CLI entry point
├── commands.txt         # Batch commands file (all modules x languages)
├── config/
│   └── settings.py      # Pydantic settings (loads .env)
├── models/
│   └── localization.py  # Data models
├── clients/
│   ├── auth_client.py   # OAuth authentication
│   ├── search_client.py # Search API client
│   └── upsert_client.py # Upsert API client
├── services/
│   └── sync_service.py  # Orchestration (fetch, transform, save, upsert)
├── requests/            # Request JSON templates
└── output/              # Generated output files
```
