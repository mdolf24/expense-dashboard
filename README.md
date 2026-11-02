# Personal Expense Analysis

A Streamlit portfolio app for exploring household spending with privacy-safe demo
data by default. It can optionally connect to a private Google Sheet.

## Features

- Dashboard with totals, category budgets, and remaining budget
- Detailed category, subcategory, shop, person, and discount analysis
- Split expenses and settlements, including exclude-from-balance expenses
- Month-to-month spending trends
- Receipt OCR entry with Google Gemini
- Claude analyst chat with a restricted Python/pandas analysis tool
- Automatic demo mode when no Google Sheets connection is configured

## Architecture

- `app.py` is the dashboard entry point.
- `pages/` contains Streamlit multipage views.
- `config.py` reads names, budgets, split ratios, and spreadsheet name from
  Streamlit secrets or an optional local `config.toml`.
- `data_loader.py` provides one data-loading path for Google Sheets and demo CSVs.
- `analysis.py` contains reusable aggregation and spreadsheet helpers.
- `demo_data/` contains three months of synthetic, fictional transactions.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The app runs immediately in demo mode. To configure a private deployment:

1. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`.
2. Fill in the `[app]` values and Google service-account fields. When using a
   private Google Sheet, set `access_password_hash` to the SHA-256 hash of a
   strong password; connected data is blocked until the password is entered.
3. Optionally add an `[anthropic]` API key for analyst chat and a Google Gemini
   key for receipt OCR.
4. Share the Google Sheet with the service-account email.

Alternatively copy `config.example.toml` to `config.toml` for non-secret app
settings. Secrets take precedence over that file.

## Demo mode

With no configured Google Sheets connection, the app loads the three CSV files in
`demo_data/`. Add Expense is read-only in this mode; dashboards, trends, split
calculations, and chat context remain available.

## Security

Never commit `.streamlit/secrets.toml`, service-account JSON files, API keys,
exports, or personal spreadsheets. The repository ignores those paths. If a
credential was ever exposed, revoke and rotate it before publishing.

The analyst chat uses a fixed read-only aggregation tool and does not execute
model-provided Python code.
