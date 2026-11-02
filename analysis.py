import pandas as pd
import os
import re

#helperji za sheet/label + discover
SHEET_RE = re.compile(r"^(?P<year>\d{4})_(?P<month>\d{2})$")
YES_VALUES = {"yes", "ja", "y", "true", "1"}


def _normalize_yes_no(value: object) -> bool:
    return str(value).strip().lower() in YES_VALUES


def _ensure_split_flags(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    if "Split" not in df.columns:
        df["Split"] = "no"
    if "Exclude_Balance" not in df.columns:
        df["Exclude_Balance"] = "no"

    df["Split"] = df["Split"].apply(_normalize_yes_no)
    df["Exclude_Balance"] = df["Exclude_Balance"].apply(_normalize_yes_no)

    return df

def sheet_name(year: int, month: int) -> str:
    return f"{year}_{month:02d}"

def period_label(year: int, month: int) -> str:
    return f"{year}-{month:02d}"

def discover_periods(data_dir: str = "data") -> dict[tuple[int, int], str]:
    """
    Returns mapping: (year, month) -> excel_path
    by scanning files like data/expenses_2026.xlsx and sheets like 2026_01.
    """
    periods: dict[tuple[int, int], str] = {}

    for fname in os.listdir(data_dir):
        if not (fname.startswith("expenses_") and fname.endswith(".xlsx")):
            continue

        path = os.path.join(data_dir, fname)

        try:
            xls = pd.ExcelFile(path)
        except Exception:
            continue

        for sh in xls.sheet_names:
            m = SHEET_RE.match(sh)
            if not m:
                continue
            year = int(m.group("year"))
            month = int(m.group("month"))
            periods[(year, month)] = path

    return periods


DATA_PATH_DEFAULT = "data/expenses_2025.xlsx"

#loading and cleaning
def load_data(path: str, year: int, month: int) -> pd.DataFrame:
    """Read Excel into a pandas DataFrame and do basic cleaning."""
    sh = sheet_name(year, month)
    df = pd.read_excel(path, sheet_name=sh)

    #date format
    df["Date"] = pd.to_datetime(df["Date"])

    #clean whitespace in text columns
    text_cols = ["Shop", "Item", "Category", "Subcategory", "Who", "Split", "Exclude_Balance"]
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    df = _ensure_split_flags(df)

    return df

def total_spent(df: pd.DataFrame) -> float:
    return df["Final_Price"].sum()


def spent_by_category(df: pd.DataFrame) -> pd.Series:
    return (
        df.groupby("Category")["Final_Price"]
        .sum()
        .sort_values(ascending=False)
    )


def spent_by_subcategory(df: pd.DataFrame) -> pd.Series:
    return (
        df.groupby("Subcategory")["Final_Price"]
        .sum()
        .sort_values(ascending=False)
    )


def spent_by_person(df: pd.DataFrame) -> pd.Series:
    return (
        df.groupby("Who")["Final_Price"]
        .sum()
        .sort_values(ascending=False)
    )


def spent_by_shop(df: pd.DataFrame) -> pd.Series:
    return (
        df.groupby("Shop")["Final_Price"]
        .sum()
        .sort_values(ascending=False)
    )

def split_summary(
    df: pd.DataFrame, split_ratios: tuple[float, float] = (0.5, 0.5)
) -> tuple[float, float, pd.DataFrame]:
    """
    Vrne:
     Gleda SAMO deljene stroške (Split == True) in vrne:
      - total_split: skupni znesek deljenih stroškov
      - total_excluded: znesek deljenih stroškov, ki so označeni kot pre-settled
      - summary DataFrame po osebah z:
          paid_for_split   (koliko je oseba plačala za deljene stroške)
          fair_share_split (koliko bi morala plačati, če se deli enakomerno)
          balance          (pozitivno = plačala preveč, negativno = plačala premalo)
    """
    df = _ensure_split_flags(df)

    if "Split" not in df.columns:
        raise ValueError("Column 'Split' not found in df")

    if "Final_Price" not in df.columns or "Who" not in df.columns:
        raise ValueError("Columns 'Final_Price' and 'Who' are required for split summary")
    
    df_split = df[df["Split"]]
    df_balance = df_split[~df_split["Exclude_Balance"]]

    if df_split.empty:
        return 0.0, 0.0, pd.DataFrame(columns=["paid_for_split", "fair_share_split", "balance"])
    
    total_split = float(df_split["Final_Price"].sum())
    total_excluded = float(df_split[df_split["Exclude_Balance"]]["Final_Price"].sum())

    if df_balance.empty:
        return total_split, total_excluded, pd.DataFrame(columns=["paid_for_split", "fair_share_split", "balance"])

    paid_for_split = df_balance.groupby("Who")["Final_Price"].sum()

    people = sorted(df_balance["Who"].dropna().unique())
    paid_for_split = paid_for_split.reindex(people, fill_value=0.0)

    balance_total = float(paid_for_split.sum())
    n_people = len(people)
    if n_people == 2 and abs(sum(split_ratios) - 1.0) < 0.001:
        fair_share_split = pd.Series(
            {person: balance_total * ratio for person, ratio in zip(people, split_ratios)},
            name="fair_share_split",
        )
    else:
        equal_share = balance_total / n_people
        fair_share_split = pd.Series({person: equal_share for person in people}, name="fair_share_split")

    balance = paid_for_split - fair_share_split
    summary = pd.DataFrame(
        {
            "paid_for_split": paid_for_split,
            "fair_share_split": fair_share_split,
            "balance": balance,
        }
    )

    return total_split, total_excluded, summary

#robust append expense
def append_expense(path: str, year: int, month: int, row: dict) -> None:
    sh = sheet_name(year, month)

    # Read existing sheet if present
    df_existing = pd.DataFrame()
    if os.path.exists(path):
        try:
            df_existing = pd.read_excel(path, sheet_name=sh)
        except ValueError:
            df_existing = pd.DataFrame()

    if isinstance(row, pd.DataFrame):
        df_new = row.copy()
    elif isinstance(row, dict):
     df_new = pd.DataFrame([row])
    else:
        raise TypeError(f"row must be dict or DataFrame, got {type(row)}")

    df_out = pd.concat([df_existing, df_new], ignore_index=True)

    # If file doesn't exist -> create it (mode="w")
    if not os.path.exists(path):
        with pd.ExcelWriter(path, engine="openpyxl", mode="w") as writer:
            df_out.to_excel(writer, sheet_name=sh, index=False)
        return

    # Else replace only that sheet (mode="a")
    with pd.ExcelWriter(path, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
        df_out.to_excel(writer, sheet_name=sh, index=False)
