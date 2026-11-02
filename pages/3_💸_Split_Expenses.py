import streamlit as st
import pandas as pd
import datetime as dt

# Import analysis functions
from analysis import (
    split_summary,
)
from config import CONFIG
from data_loader import get_google_spreadsheet, load_month, is_demo_mode
from config import require_access

st.set_page_config(page_title="Split Expenses", page_icon="💸")
require_access()

st.title("💸 Split Expenses & Settlements")
sh = get_google_spreadsheet() if not is_demo_mode() else None

# ────────────────────────────────────────────────────────────────────────────
# Load gspread client and get selected month
# ────────────────────────────────────────────────────────────────────────────

# Get selected month from session state (set by home page), fallback to current
if "selected_worksheet" in st.session_state:
    selected_worksheet = st.session_state["selected_worksheet"]
else:
    # Fallback to current month
    today = dt.date.today()
    selected_worksheet = today.strftime("%Y_%m")

st.caption(f"📅 Showing data for: **{selected_worksheet}**")

# ────────────────────────────────────────────────────────────────────────────
# Load data from selected worksheet
# ────────────────────────────────────────────────────────────────────────────

df = load_month(selected_worksheet)
if df.empty:
    st.warning(f"No data found for {selected_worksheet}. Select a month from home page.")
    st.stop()
df = df.sort_values("Date", ascending=False)

# ────────────────────────────────────────────────────────────────────────────
# Calculate split summary
# ────────────────────────────────────────────────────────────────────────────

if "Exclude_Balance" not in df.columns:
    df["Exclude_Balance"] = "no"
if "Split" not in df.columns:
    df["Split"] = "no"

total_split, total_excluded, split_df = split_summary(df, CONFIG.split_ratios)
total_balance_relevant = max(total_split - total_excluded, 0.0)
excluded_df = df[
    df["Split"].astype(str).str.lower().eq("yes")
    & df["Exclude_Balance"].astype(str).str.lower().eq("yes")
].copy()

# ────────────────────────────────────────────────────────────────────────────
# Current split balance section
# ────────────────────────────────────────────────────────────────────────────

st.subheader("💰 Current Split Balance")

st.caption("Total split expenses includes pre-settled items marked as excluded from balance.")

metric_col1, metric_col2, metric_col3 = st.columns(3)

with metric_col1:
    st.metric("Total split expenses", f"€{total_split:.2f}")

with metric_col2:
    st.metric("Pre-settled expenses", f"€{total_excluded:.2f}")

with metric_col3:
    st.metric("Balance-relevant split expenses", f"€{total_balance_relevant:.2f}")

if split_df.empty:
    if total_excluded > 0:
        st.info(
            "✅ No balance-relevant split expenses this month. Pre-settled expenses are excluded from who-owes-whom calculations."
        )
        with st.expander("📦 Pre-settled expenses"):
            if excluded_df.empty:
                st.info("No pre-settled expenses found.")
            else:
                display_cols = [col for col in ["Date", "Who", "Shop", "Item", "Final_Price"] if col in excluded_df.columns]
                st.dataframe(
                    excluded_df[display_cols].sort_values("Date", ascending=False),
                    use_container_width=True,
                )
        st.stop()

    st.info("✅ No split expenses this month. Everyone paid their own way!")
    st.stop()

st.write(
    "**Balance legend:** "
    "🟢 Positive = paid more than fair share (owed by others) | "
    "🔴 Negative = paid less than fair share (owes others)"
)

# Display balance table
st.dataframe(
    split_df.style.format(
        {
            "paid_for_split": "€{:.2f}",
            "fair_share_split": "€{:.2f}",
            "balance": "€{:.2f}",
        }
    ),
    use_container_width=True
)

st.markdown("---")

# ────────────────────────────────────────────────────────────────────────────
# Who paid for split expenses bar chart
# ────────────────────────────────────────────────────────────────────────────

st.subheader("📊 Who Paid for Balance-Relevant Split Expenses")
st.bar_chart(split_df["paid_for_split"])

if total_excluded > 0:
    st.caption("Pre-settled expenses are shown separately in the expander below.")

with st.expander("📦 Show pre-settled expenses"):
    if excluded_df.empty:
        st.info("No pre-settled expenses found.")
    else:
        display_cols = [col for col in ["Date", "Who", "Shop", "Item", "Final_Price"] if col in excluded_df.columns]
        st.dataframe(
            excluded_df[display_cols].sort_values("Date", ascending=False),
            use_container_width=True,
        )

st.markdown("---")

# ────────────────────────────────────────────────────────────────────────────
# Manual payment adjustments
# ────────────────────────────────────────────────────────────────────────────

st.subheader("💳 Record Payments & Loans")
st.caption("Track settlements of split expenses or direct loans between participants")
if is_demo_mode():
    st.info("Demo mode is read-only. Configure Google Sheets to persist payment adjustments.")

# Payments are stored in a dedicated worksheet so they survive app restarts.
PAYMENTS_WORKSHEET = "Payments"
PAYMENT_COLUMNS = ["Date", "Who", "Amount", "Type", "Expense_Month"]


def load_payments() -> list[dict]:
    if is_demo_mode():
        return []
    try:
        payments_worksheet = sh.worksheet(PAYMENTS_WORKSHEET)
    except Exception:
        return []

    payments_df = pd.DataFrame(payments_worksheet.get_all_records())
    if payments_df.empty or "Expense_Month" not in payments_df.columns:
        return []

    payments_df = payments_df[
        payments_df["Expense_Month"].astype(str) == selected_worksheet
    ].copy()
    if payments_df.empty:
        return []

    if "Type" not in payments_df.columns:
        payments_df["Type"] = "settlement"
    payments_df["Amount"] = pd.to_numeric(payments_df["Amount"], errors="coerce").fillna(0.0)
    return [
        {
            "date": str(row["Date"]),
            "who": str(row["Who"]),
            "amount": float(row["Amount"]),
            "type": str(row["Type"] or "settlement"),
        }
        for _, row in payments_df.iterrows()
    ]


def save_payments(payments_list: list[dict]) -> None:
    if is_demo_mode():
        st.warning("Payment saving is unavailable in demo mode.")
        return
    try:
        payments_worksheet = sh.worksheet(PAYMENTS_WORKSHEET)
    except Exception:
        payments_worksheet = sh.add_worksheet(
            title=PAYMENTS_WORKSHEET,
            rows=1000,
            cols=len(PAYMENT_COLUMNS),
        )

    rows = [PAYMENT_COLUMNS]
    for payment in payments_list:
        rows.append([
            payment["date"],
            payment["who"],
            float(payment["amount"]),
            payment.get("type", "settlement"),
            selected_worksheet,
        ])

    all_payments_df = pd.DataFrame(payments_worksheet.get_all_records())
    if not all_payments_df.empty and "Expense_Month" in all_payments_df.columns:
        all_payments_df = all_payments_df[
            all_payments_df["Expense_Month"].astype(str) != selected_worksheet
        ]
        for column in PAYMENT_COLUMNS:
            if column not in all_payments_df.columns:
                all_payments_df[column] = ""
        rows.extend(all_payments_df[PAYMENT_COLUMNS].fillna("").values.tolist())

    payments_worksheet.clear()
    payments_worksheet.update(rows, "A1")


# Initialize session state from the selected month's Payments worksheet.
payment_state_key = f"payment_list_{selected_worksheet}"
if payment_state_key not in st.session_state:
    st.session_state[payment_state_key] = load_payments()

# Add new payment form
st.write("**Add a payment:**")
with st.form("add_payment_form", clear_on_submit=True):
    col_date, col_who, col_type, col_amount = st.columns([2, 2, 1.5, 1])

    with col_date:
        payment_date = st.date_input("Date", value=dt.date.today())

    with col_who:
        # Get list of people from split_df
        people_list = list(split_df.index)
        who_paid = st.selectbox("Who paid", people_list)

    with col_type:
        payment_type = st.selectbox(
            "Type",
            ["settlement", "loan"],
            help="settlement: payment toward split expenses | loan: direct loan"
        )

    with col_amount:
        payment_amount = st.number_input("Amount (EUR)", min_value=0.0, step=10.0)

    submitted = st.form_submit_button("➕ Add payment", use_container_width=True)

    if submitted and payment_amount > 0:
        new_payment = {
            "date": payment_date.isoformat(),
            "who": who_paid,
            "amount": float(payment_amount),
            "type": payment_type,
        }
        st.session_state[payment_state_key].append(new_payment)
        save_payments(st.session_state[payment_state_key])
        type_label = "Settlement" if payment_type == "settlement" else "Loan"
        st.success(f"✅ {type_label} of €{payment_amount:.2f} by {who_paid} recorded!")
        st.rerun()

# Display payment history
if st.session_state[payment_state_key]:
    st.write("**Payment history:**")

    # Convert to DataFrame for display
    payments_df = pd.DataFrame(st.session_state[payment_state_key])
    payments_df["date"] = pd.to_datetime(payments_df["date"]).dt.date
    payments_df = payments_df.sort_values("date", ascending=False)

    # Ensure type column exists (backwards compatibility)
    if "type" not in payments_df.columns:
        payments_df["type"] = "settlement"

    # Display each payment with a delete button
    for idx, payment in payments_df.iterrows():
        col_info, col_delete = st.columns([5, 1])

        with col_info:
            payment_type = payment.get("type", "settlement")
            type_icon = "🔄" if payment_type == "settlement" else "💳"
            type_label = "Settlement" if payment_type == "settlement" else "Loan"
            st.text(
                f"{type_icon} {type_label} | 📅 {payment['date']} | 👤 {payment['who']} | 💶 €{payment['amount']:.2f}"
            )

        with col_delete:
            if st.button("🗑️", key=f"delete_{idx}"):
                # Remove this payment
                st.session_state[payment_state_key] = [
                    p
                    for i, p in enumerate(st.session_state[payment_state_key])
                    if i != idx
                ]
                save_payments(st.session_state[payment_state_key])
                st.rerun()

    # Calculate totals by type
    total_paid = payments_df["amount"].sum()
    settlements = payments_df[payments_df["type"] == "settlement"]["amount"].sum()
    loans = payments_df[payments_df["type"] == "loan"]["amount"].sum()
    
    # Display three metrics
    metric_col1, metric_col2, metric_col3 = st.columns(3)
    with metric_col1:
        st.metric("Total payments & loans", f"€{total_paid:.2f}")
    with metric_col2:
        st.metric("Settlements", f"€{settlements:.2f}")
    with metric_col3:
        st.metric("Loans", f"€{loans:.2f}")
else:
    st.info("No payments recorded yet.")
    total_paid = 0.0

st.markdown("---")

# ────────────────────────────────────────────────────────────────────────────
# Calculate adjusted balances
# ────────────────────────────────────────────────────────────────────────────

adjusted_df = split_df.copy()
adjusted_df["adjusted_balance"] = adjusted_df["balance"].copy()

# Distribute the payment proportionally based on original balances
if total_paid > 0:
    # Find who owes (negative) and who is owed (positive)
    total_owed = adjusted_df[adjusted_df["balance"] < 0]["balance"].sum()  # negative
    total_to_receive = adjusted_df[adjusted_df["balance"] > 0]["balance"].sum()  # positive

    # Payment reduces both sides equally
    payment_to_distribute = min(total_paid, abs(total_owed), total_to_receive)

    for person in adjusted_df.index:
        balance = float(adjusted_df.loc[person, "balance"])  # type: ignore[arg-type]
        if balance < 0:
            # Person owes money - reduce their debt
            adjusted_df.loc[person, "adjusted_balance"] = (
                balance + payment_to_distribute
            )
        elif balance > 0:
            # Person is owed money - reduce what they're owed
            adjusted_df.loc[person, "adjusted_balance"] = (
                balance - payment_to_distribute
            )

# ────────────────────────────────────────────────────────────────────────────
# Settlement suggestions
# ────────────────────────────────────────────────────────────────────────────

st.subheader("🤝 Settlement Suggestions")

# Display comparison side by side
col_original, col_adjusted = st.columns(2)

with col_original:
    st.write("**Original balance**")
    st.dataframe(
        split_df[["balance"]].style.format({"balance": "€{:.2f}"}),
        use_container_width=True,
    )

with col_adjusted:
    st.write("**After recorded payments**")
    st.dataframe(
        adjusted_df[["adjusted_balance"]].style.format(
            {"adjusted_balance": "€{:.2f}"}
        ),
        use_container_width=True,
    )

st.write("**Current status:**")
for person, row in adjusted_df.iterrows():
    adj_bal = row["adjusted_balance"]
    if abs(adj_bal) < 0.01:
        st.success(f"✅ {person}: Settled up!")
    elif adj_bal > 0:
        st.info(f"💰 {person} is owed: **€{adj_bal:.2f}**")
    else:
        st.warning(f"💸 {person} owes: **€{abs(adj_bal):.2f}**")

st.markdown("---")

# ────────────────────────────────────────────────────────────────────────────
# Quick settlement actions
# ────────────────────────────────────────────────────────────────────────────

st.subheader("⚡ Quick Actions")

col_settle, col_reset = st.columns(2)

with col_settle:
    # Calculate total amount needed to fully settle
    total_debt = abs(split_df[split_df["balance"] < 0]["balance"].sum())
    remaining_to_settle = total_debt - total_paid
    if st.button(
        f"✅ Settle balance (€{remaining_to_settle:.2f})",
        type="primary",
        use_container_width=True,
    ):
        if remaining_to_settle > 0:
            new_payment = {
                "date": dt.date.today().isoformat(),
                "who": "Settlement",
                "amount": float(remaining_to_settle),
                "type": "settlement",
            }
            st.session_state[payment_state_key].append(new_payment)
            save_payments(st.session_state[payment_state_key])
            st.success("🎉 All balances marked as settled!")
            st.rerun()
        else:
            st.info("Already settled up!")

with col_reset:
    if st.button("🔄 Clear all payments", use_container_width=True):
        st.session_state[payment_state_key] = []
        save_payments([])
        st.rerun()

st.markdown("---")

# ────────────────────────────────────────────────────────────────────────────
# Raw data
# ────────────────────────────────────────────────────────────────────────────

with st.expander("📋 Show raw expense data"):
    st.dataframe(df, use_container_width=True)
