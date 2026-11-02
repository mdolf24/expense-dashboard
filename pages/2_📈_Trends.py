import streamlit as st
import pandas as pd
import datetime as dt

# Import analysis functions
from analysis import (
    total_spent,
    spent_by_category,
)
from data_loader import available_months, load_month
from config import require_access

st.set_page_config(page_title="Trends & Comparisons", page_icon="📈")
require_access()

st.title("📈 Historical Trends & Comparisons")

# ────────────────────────────────────────────────────────────────────────────
# Load gspread client and get available months
# ────────────────────────────────────────────────────────────────────────────

available_worksheets = available_months()
if len(available_worksheets) < 2:
    st.info("📊 You need at least 2 months of data to see trends.")
    st.stop()

# ────────────────────────────────────────────────────────────────────────────
# Month selector
# ────────────────────────────────────────────────────────────────────────────

st.subheader("Select months to compare")

col1, col2 = st.columns(2)

with col1:
    month1 = st.selectbox(
        "Month 1:",
        available_worksheets,
        index=0,
        key="month1_selector"
    )

with col2:
    # Default to previous month if available
    default_month2_idx = 1 if len(available_worksheets) > 1 else 0
    month2 = st.selectbox(
        "Month 2:",
        available_worksheets,
        index=default_month2_idx,
        key="month2_selector"
    )

# Swap if month1 > month2 (ensure chronological order for display)
if month1 is not None and month2 is not None and month1 < month2:
    month1, month2 = month2, month1

st.caption(f"Comparing **{month2}** → **{month1}** (older → newer)")

# ────────────────────────────────────────────────────────────────────────────
# Load data for both months
# ────────────────────────────────────────────────────────────────────────────

df1 = load_month(month1)
df2 = load_month(month2)
if df1.empty or df2.empty:
    st.warning("One or both months have no data.")
    st.stop()

# ────────────────────────────────────────────────────────────────────────────
# Comparison metrics (top)
# ────────────────────────────────────────────────────────────────────────────

st.markdown("---")
st.subheader("💰 Spending Overview")

total1 = total_spent(df1)
total2 = total_spent(df2)
delta = total1 - total2
delta_pct = (delta / total2 * 100) if total2 > 0 else 0.0

col_m1, col_m2, col_delta = st.columns(3)

with col_m1:
    st.metric(f"**{month1}** Total", f"€{total1:.2f}")

with col_m2:
    st.metric(f"**{month2}** Total", f"€{total2:.2f}")

with col_delta:
    # Color based on increase/decrease
    delta_color = "normal" if delta <= 0 else "off"
    delta_label = "↓ Decrease" if delta <= 0 else "↑ Increase"
    st.metric(
        "Change",
        f"€{abs(delta):.2f}",
        delta=f"{delta_pct:+.1f}%",
        delta_color=delta_color,
    )

# ────────────────────────────────────────────────────────────────────────────
# Category comparison table
# ────────────────────────────────────────────────────────────────────────────

st.markdown("---")
st.subheader("📊 Category Breakdown")

# Get spending by category for both months
by_cat1 = spent_by_category(df1)
by_cat2 = spent_by_category(df2)

# Create comparison dataframe
all_categories = sorted(list(set(by_cat1.index) | set(by_cat2.index)))
comparison_df = pd.DataFrame(
    {
        month1: [by_cat1.get(cat, 0.0) for cat in all_categories],
        month2: [by_cat2.get(cat, 0.0) for cat in all_categories],
    },
    index=all_categories,
)

comparison_df["Change (€)"] = comparison_df[month1] - comparison_df[month2]
comparison_df["Change (%)"] = (
    (comparison_df["Change (€)"] / comparison_df[month2] * 100)
    .where(comparison_df[month2] != 0, 0.0)
)

# Sort by absolute change (biggest changes first)
comparison_df = comparison_df.sort_values("Change (€)", ascending=False, key=abs)

# Display table with styling
def highlight_change(val):
    if pd.isna(val):
        return ""
    if val > 0:
        return "color: red; font-weight: bold;"
    elif val < 0:
        return "color: green; font-weight: bold;"
    return ""

styled_comparison = comparison_df.style.format(
    {
        month1: "€{:.2f}",
        month2: "€{:.2f}",
        "Change (€)": "€{:+.2f}",
        "Change (%)": "{:+.1f}%",
    }
).map(highlight_change, subset=["Change (€)"])

st.dataframe(styled_comparison, use_container_width=True)

# ────────────────────────────────────────────────────────────────────────────
# Side-by-side bar chart
# ────────────────────────────────────────────────────────────────────────────

st.markdown("---")
st.subheader("📈 Visual Comparison")

# Prepare data for grouped bar chart
chart_df = comparison_df[[month1, month2]].copy()
if month1 is not None:
    chart_df = chart_df.sort_values(by=month1, ascending=False)  # Sort by month1 for better readability

st.bar_chart(chart_df)

# ────────────────────────────────────────────────────────────────────────────
# Auto-generated insights
# ────────────────────────────────────────────────────────────────────────────

st.markdown("---")
st.subheader("💡 Key Insights")

insights = []

# Overall trend
if delta > 0:
    insights.append(
        f"📈 **Overall spending increased** by €{abs(delta):.2f} ({delta_pct:+.1f}%) from {month2} to {month1}."
    )
else:
    insights.append(
        f"📉 **Overall spending decreased** by €{abs(delta):.2f} ({abs(delta_pct):.1f}%) from {month2} to {month1}."
    )

# Top increases and decreases
changes_sorted = comparison_df["Change (€)"].sort_values(ascending=False)

if len(changes_sorted) > 0 and changes_sorted.iloc[0] > 0:
    top_increase_cat = changes_sorted.index[0]
    top_increase_val = changes_sorted.iloc[0]
    top_increase_pct = comparison_df.loc[top_increase_cat, "Change (%)"]
    insights.append(
        f"🔴 **Biggest increase:** {top_increase_cat} (+€{top_increase_val:.2f}, {top_increase_pct:+.1f}%)"
    )

if len(changes_sorted) > 0 and changes_sorted.iloc[-1] < 0:
    top_decrease_cat = changes_sorted.index[-1]
    top_decrease_val = changes_sorted.iloc[-1]
    top_decrease_pct = comparison_df.loc[top_decrease_cat, "Change (%)"]
    insights.append(
        f"🟢 **Biggest decrease:** {top_decrease_cat} (€{top_decrease_val:.2f}, {top_decrease_pct:.1f}%)"
    )

# Categories with no change
no_change_cats = comparison_df[comparison_df["Change (€)"].abs() < 0.01]
if len(no_change_cats) > 0:
    insights.append(
        f"🟡 **Stable categories:** {', '.join(no_change_cats.index[:3])} stayed consistent across months"
    )

# Most expensive category in latest month
most_expensive = by_cat1.idxmax() if len(by_cat1) > 0 else None
if most_expensive:
    most_expensive_val = by_cat1[most_expensive]
    pct_of_total = (most_expensive_val / total1 * 100) if total1 > 0 else 0
    insights.append(
        f"💸 **Top category in {month1}:** {most_expensive} (€{most_expensive_val:.2f}, {pct_of_total:.1f}% of total)"
    )

# Display insights
for insight in insights:
    st.write(insight)

# ────────────────────────────────────────────────────────────────────────────
# Raw data expander
# ────────────────────────────────────────────────────────────────────────────

with st.expander("📋 Show raw data"):
    col_raw1, col_raw2 = st.columns(2)

    with col_raw1:
        st.write(f"**{month1} - {len(df1)} records**")
        st.dataframe(df1, use_container_width=True)

    with col_raw2:
        st.write(f"**{month2} - {len(df2)} records**")
        st.dataframe(df2, use_container_width=True)
