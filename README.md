# Localization Sync Framework

A CLI tool to search localizations from one environment and upsert them to another, with automatic locale transformation.

## How It Works

```
SOURCE_ENV (e.g. QA)                         TARGET_ENV (e.g. UAT)
       |                                            |
  1. Login to target env (get auth token)           |
  2. Search localizations (en_MZ)                   |
  3. Save search response to output/                |
  4. Transform locale (en_MZ -> en_IN)              |
  5. Save upsert request body to output/            |
  6. Upsert transformed messages  ───────────>  POST /localization/messages/v1/_upsert
```

## Prerequisites

- Python 3.10+
- pip

## Setup

### 1. Clone and navigate to the project

```bash
cd localization_framework
```

### 2. Create a virtual environment

```bash
python -m venv venv
source venv/bin/activate        # Linux/Mac
# venv\Scripts\activate         # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment

Copy the example env file and edit it:

```bash
cp .env.example .env
```

Edit `.env` and set your source and target environments:

```env
# Which environment to search FROM
SOURCE_ENV=qa

# Which environment to upsert TO
TARGET_ENV=uat

# Auth credentials
AUTH_USERNAME=LNMZ
AUTH_PASSWORD=eGov@1234
```

Each environment (UAT, DEMO, QA, PROD) is configured with its own URL, tenant ID, locales, and API key.

## Commands

### Upsert (Search + Transform + Upsert)

The main command. Searches localizations from `SOURCE_ENV`, transforms the locale, and upserts to `TARGET_ENV`.

```bash
# Upsert English localizations
python main.py upsert --lang en

# Upsert French localizations
python main.py upsert --lang fr

# Upsert Portuguese localizations
python main.py upsert --lang pt

# Filter by module
python main.py upsert --lang en --module hcm-common

# Custom batch size
python main.py upsert --lang en --batch-size 50

# Verbose logging
python main.py upsert --lang en -v
```

**What happens internally:**
1. Reads `SOURCE_ENV` and `TARGET_ENV` from `.env`
2. Logs in to the target environment (gets auth token)
3. Searches localizations from the source environment
4. Saves the raw search response to `output/`
5. Transforms locale (e.g., `en_MZ` -> `en_IN`)
6. Saves the transformed upsert request body to `output/`
7. Upserts the transformed messages to the target environment in batches

### Search (Fetch and Save Only)

Fetches localizations from `SOURCE_ENV` and saves them to files without upserting. Useful to review data before pushing.

```bash
# Search and save
python main.py search --lang en

# Filter by module
python main.py search --lang en --module hcm-common

# Custom output directory
python main.py search --lang en --output-dir my_output
```

Output files are saved to `output/`:
- `{timestamp}_search_response_{env}_{locale}.json` - raw search response
- `{timestamp}_upsert_body_{env}_{locale}.json` - transformed upsert request body

### Upsert from File

Upsert localizations from a previously saved JSON file to `TARGET_ENV`.

```bash
python main.py upsert-file --input output/20260209_upsert_body_uat_en_IN.json
```

The input JSON file must contain:
```json
{
  "tenantId": "mz",
  "module": "hcm-common",
  "locale": "en_IN",
  "messages": [
    {
      "code": "HOME_DASHBOARD_LABEL",
      "message": "Dashboard",
      "module": "hcm-common",
      "locale": "en_IN"
    }
  ]
}
```

### Login

Test authentication against an environment.

```bash
# Login to TARGET_ENV (from .env)
python main.py login --username LNMZ

# Login to a specific environment
python main.py login --username LNMZ --env qa
```

### Validate

Check that your configuration and request files are valid.

```bash
python main.py validate
```

## Configuration

All configuration is in the `.env` file.

### Environment Selection

| Variable | Description | Example |
|---|---|---|
| `SOURCE_ENV` | Environment to search from | `qa` |
| `TARGET_ENV` | Environment to upsert to | `uat` |

### Authentication

| Variable | Description |
|---|---|
| `AUTH_CLIENT_CREDENTIALS` | Base64 encoded client credentials |
| `AUTH_USERNAME` | Username for OAuth login |
| `AUTH_PASSWORD` | Password for OAuth login |

### Per-Environment Config

Each environment (UAT, DEMO, QA, PROD) has:

| Variable | Description | Example |
|---|---|---|
| `{ENV}_API_URL` | Base API URL | `https://unified-uat.digit.org` |
| `{ENV}_TENANT_ID` | Tenant ID | `mz` |
| `{ENV}_LOCALE_ENGLISH` | English locale code | `en_IN` |
| `{ENV}_LOCALE_FRENCH` | French locale code | `fr_IN` |
| `{ENV}_LOCALE_PORTUGUESEH` | Portuguese locale code | `pt_IN` |
| `{ENV}_API_KEY` | API key (optional) | |

### Supported Languages

| Code | Language |
|---|---|
| `en` | English |
| `fr` | French |
| `pt` | Portuguese |

### Supported Environments

| Name | Description |
|---|---|
| `uat` | UAT environment |
| `demo` | Demo environment |
| `qa` | QA environment |
| `prod` | Production environment |

## Project Structure

```
localization_framework/
├── main.py                  # CLI entry point (commands: upsert, search, upsert-file, login, validate)
├── requirements.txt         # Python dependencies
├── .env.example             # Environment configuration template
├── config/
│   └── settings.py          # Pydantic settings (loads .env)
├── models/
│   └── localization.py      # Data models (LocalizationMessage, RequestInfo, etc.)
├── clients/
│   ├── auth_client.py       # OAuth authentication client
│   ├── search_client.py     # Search API client (POST /localization/messages/v1/_search)
│   └── upsert_client.py     # Upsert API client (POST /localization/messages/v1/_upsert)
├── services/
│   └── sync_service.py      # Orchestration (fetch, transform, save, upsert)
├── requests/                # Request JSON templates
│   ├── auth.json
│   ├── search.json
│   └── upsert.json
└── output/                  # Generated output files (search responses, upsert bodies)
```

## Examples

### Search from QA and upsert to UAT (English)

```bash
# Set in .env:
# SOURCE_ENV=qa
# TARGET_ENV=uat

python main.py upsert --lang en
```

### Search from PROD and upsert to DEMO (French)

```bash
# Set in .env:
# SOURCE_ENV=prod
# TARGET_ENV=demo

python main.py upsert --lang fr
```

### Two-step workflow: review then upsert

```bash
# Step 1: Search and save (review the output files)
python main.py search --lang en

# Step 2: Review output/
# Step 3: Upsert from the saved file
python main.py upsert-file --input output/20260209_upsert_body_uat_en_IN.json
```

### Using a custom env file

```bash
python main.py upsert --lang en --env-file .env.prod
```
# Localization
