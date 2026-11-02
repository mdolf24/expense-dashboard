import streamlit as st
import pandas as pd
import datetime as dt

from analysis import (
    total_spent,
    spent_by_category,
)
from config import CONFIG, require_access
from data_loader import available_months, is_demo_mode, load_month

MONTHLY_BUDGET = CONFIG.monthly_budgets

st.set_page_config(page_title="Personal Expense Dashboard", layout="wide")
require_access()

st.title(f"{CONFIG.people[0]} and {CONFIG.people[1]}'s expense dashboard")
st.caption("Demo data" if is_demo_mode() else f"Live data from {CONFIG.spreadsheet_name or 'Google Sheets'}")

months = available_months()
st.sidebar.header("Select month")
selected_worksheet = st.sidebar.selectbox("Month", months, index=0)
st.session_state["selected_worksheet"] = selected_worksheet
df = load_month(selected_worksheet)
st.caption(f"Showing data from: **{selected_worksheet}**")

# Convert Date column to datetime
if 'Date' in df.columns:
    df['Date'] = pd.to_datetime(df['Date'])



#load data
st.sidebar.header("Data info")
st.sidebar.write(f"Rows: {len(df)}")
st.sidebar.write(f"Date range: {df['Date'].min().date()} -> {df['Date'].max().date()}")

#top metric
total = total_spent(df)
st.metric("Total spent (EUR)", f"{total:.2f}")

by_cat = spent_by_category(df)

st.subheader("💰 Budget tracking")
total_budget = float(sum(MONTHLY_BUDGET.values()))
spent_in_budget = float(sum(float(by_cat.get(cat, 0.0)) for cat in MONTHLY_BUDGET))
remaining_budget = total_budget - spent_in_budget

budget_col1, budget_col2 = st.columns(2)
with budget_col1:
    st.metric("Total budget", f"{total_budget:.2f} EUR")
with budget_col2:
    st.metric("Remaining amount", f"{remaining_budget:.2f} EUR")

for category, budget in MONTHLY_BUDGET.items():
    spent = float(by_cat.get(category, 0.0))
    usage = (spent / budget) if budget > 0 else 0.0

    if usage < 0.9:
        status = "🟢"
    elif usage <= 1.0:
        status = "🟡"
    else:
        status = "🔴"

    st.write(f"{status} **{category}**: {spent:.2f} / {budget:.2f} EUR")
    st.progress(min(usage, 1.0))

    if usage > 1.0:
        over_by = spent - budget
        st.warning(f"{category} is over budget by {over_by:.2f} EUR")

st.markdown("---")

# Top 3 categories preview
st.subheader("📊 Top 3 categories")
top_3 = by_cat.head(3)
st.dataframe(top_3.rename("EUR"), use_container_width=True)

st.info("💡 Go to **Analysis** page for detailed breakdowns, charts, split expenses, and payment tracking.")
