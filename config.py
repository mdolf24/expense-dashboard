"""Application configuration with safe demo defaults."""

from dataclasses import dataclass
import hashlib
import hmac
from pathlib import Path
import tomllib
from typing import Any

import streamlit as st


ROOT = Path(__file__).parent


@dataclass(frozen=True)
class AppConfig:
    people: tuple[str, str] = ("Alex", "Jordan")
    monthly_budgets: dict[str, float] | None = None
    split_ratios: tuple[float, float] = (0.5, 0.5)
    spreadsheet_name: str = ""
    access_password_hash: str = ""

    def __post_init__(self) -> None:
        if self.monthly_budgets is None:
            object.__setattr__(
                self,
                "monthly_budgets",
                {"groceries": 400.0, "household": 100.0, "eating_out": 200.0, "housing": 1200.0},
            )


def _read_file_config() -> dict[str, Any]:
    path = ROOT / "config.toml"
    if not path.exists():
        return {}
    with path.open("rb") as config_file:
        return tomllib.load(config_file).get("app", {})


def get_config() -> AppConfig:
    values: dict[str, Any] = _read_file_config()
    try:
        values.update(dict(st.secrets.get("app", {})))
    except Exception:
        pass

    people = tuple(
        name.strip()
        for name in (values.get("person_one", ""), values.get("person_two", ""))
        if str(name).strip()
    )
    if len(people) != 2:
        people = AppConfig.people

    budgets = values.get("monthly_budgets")
    if not isinstance(budgets, dict) or not budgets:
        budgets = None
    else:
        budgets = {str(key): float(value) for key, value in budgets.items()}

    ratios = values.get("split_ratios", [0.5, 0.5])
    if not isinstance(ratios, (list, tuple)) or len(ratios) != 2:
        ratios = [0.5, 0.5]

    return AppConfig(
        people=(people[0], people[1]),
        monthly_budgets=budgets,
        split_ratios=(float(ratios[0]), float(ratios[1])),
        spreadsheet_name=str(values.get("spreadsheet_name", "")).strip(),
        access_password_hash=str(values.get("access_password_hash", "")).strip(),
    )


def google_sheets_configured() -> bool:
    try:
        connection = st.secrets.get("connections", {}).get("gsheets", {})
        return bool(connection.get("spreadsheet") and connection.get("private_key"))
    except Exception:
        return False


CONFIG = get_config()


def require_access() -> None:
    """Require a configured password before exposing a connected private sheet."""
    if not google_sheets_configured():
        return
    if not CONFIG.access_password_hash:
        st.error("Private data is configured but no access password hash is set.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("Private expense dashboard")
    password = st.text_input("Access password", type="password")
    if st.button("Sign in"):
        digest = hashlib.sha256(password.encode()).hexdigest()
        if hmac.compare_digest(digest, CONFIG.access_password_hash):
            st.session_state["authenticated"] = True
            st.rerun()
        st.error("Invalid access password.")
    st.stop()
