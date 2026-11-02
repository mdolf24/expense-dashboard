"""Load Google Sheets data when configured, otherwise use the public demo data."""

from pathlib import Path
import re

import pandas as pd
import streamlit as st

from config import google_sheets_configured


DATA_COLUMNS = [
    "Month", "Date", "Shop", "Item", "Category", "Subcategory", "Price",
    "Discount", "Final_Price", "Who", "Split", "Exclude_Balance",
]
DEMO_DIR = Path(__file__).parent / "demo_data"


def _clean(dataframe: pd.DataFrame, month: str | None = None) -> pd.DataFrame:
    frame = dataframe.copy()
    if month is not None:
        frame["Month"] = month
    for column in DATA_COLUMNS:
        if column not in frame:
            frame[column] = "no" if column in {"Split", "Exclude_Balance"} else ""
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    for column in ("Price", "Discount", "Final_Price"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    return frame.reindex(columns=DATA_COLUMNS)


def _load_demo() -> pd.DataFrame:
    files = sorted(DEMO_DIR.glob("*.csv"))
    if not files:
        return pd.DataFrame(columns=DATA_COLUMNS)
    return pd.concat(
        [_clean(pd.read_csv(path), path.stem.removeprefix("expenses_")) for path in files],
        ignore_index=True,
    )


def get_google_spreadsheet():
    import gspread
    from google.oauth2.service_account import Credentials

    connection = dict(st.secrets["connections"]["gsheets"])
    spreadsheet_url = connection.pop("spreadsheet")
    credentials = Credentials.from_service_account_info(
        connection,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )
    match = re.search(r"/d/([^/]+)", spreadsheet_url)
    if not match:
        raise ValueError("The configured spreadsheet URL does not contain a spreadsheet ID.")
    return gspread.authorize(credentials).open_by_key(match.group(1))


def _load_google() -> pd.DataFrame:
    spreadsheet = get_google_spreadsheet()
    frames = []
    for worksheet in spreadsheet.worksheets():
        if re.fullmatch(r"\d{4}_\d{2}", worksheet.title):
            frame = pd.DataFrame(worksheet.get_all_records())
            if not frame.empty:
                frames.append(_clean(frame, worksheet.title.replace("_", "-")))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=DATA_COLUMNS)


@st.cache_data(ttl=300)
def load_all_months() -> pd.DataFrame:
    if google_sheets_configured():
        try:
            return _load_google()
        except Exception as error:
            st.warning(f"Google Sheets unavailable; using demo data instead ({error}).")
    return _load_demo()


def available_months() -> list[str]:
    return sorted(load_all_months()["Month"].dropna().astype(str).unique(), reverse=True)


def load_month(month: str) -> pd.DataFrame:
    return load_all_months().loc[lambda frame: frame["Month"].astype(str).eq(month)].copy()


def is_demo_mode() -> bool:
    return not google_sheets_configured()
