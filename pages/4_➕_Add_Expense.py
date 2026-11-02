import streamlit as st
import pandas as pd
import datetime as dt
import json
import os
import re
from config import CONFIG, google_sheets_configured, require_access

st.set_page_config(page_title="Add Expense", page_icon="➕")
require_access()

st.title("➕ Add New Expense")

# ────────────────────────────────────────────────────────────────────────────
# Load gspread client and get selected month
# ────────────────────────────────────────────────────────────────────────────

sh = None
conn = None
if google_sheets_configured():
  try:
    from streamlit_gsheets import GSheetsConnection
    from google.oauth2.service_account import Credentials
    import gspread

    creds_dict = dict(st.secrets["connections"]["gsheets"])
    creds_dict.pop("spreadsheet", None)
    credentials = Credentials.from_service_account_info(
        creds_dict,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )

    gc = gspread.authorize(credentials)
    conn = st.connection("gsheets", type=GSheetsConnection)
    spreadsheet_url = st.secrets["connections"]["gsheets"]["spreadsheet"]
    match = re.search(r"/d/([^/]+)", spreadsheet_url)
    spreadsheet_id = match.group(1) if match else None
    if not spreadsheet_id:
        st.error("Could not extract spreadsheet ID from URL")
        st.stop()

    sh = gc.open_by_key(spreadsheet_id)
  except Exception as e:
    st.error(f"Error initializing Google Sheets: {e}")
else:
    st.info("Demo mode is read-only. Configure Google Sheets to save expenses.")

# Get selected month from session state (set by home page), fallback to current
if "selected_worksheet" in st.session_state:
    selected_worksheet = st.session_state["selected_worksheet"]
else:
    # Fallback to current month
    today = dt.date.today()
    selected_worksheet = today.strftime("%Y_%m")

st.info(f"📅 Adding expenses to: **{selected_worksheet}**")


def ensure_balance_columns(dataframe: pd.DataFrame) -> pd.DataFrame:
    dataframe = dataframe.copy()
    if "Split" not in dataframe.columns:
        dataframe["Split"] = "no"
    if "Exclude_Balance" not in dataframe.columns:
        dataframe["Exclude_Balance"] = "no"
    return dataframe

# ────────────────────────────────────────────────────────────────────────────
# SECTION 1: Bulk Receipt Upload
# ────────────────────────────────────────────────────────────────────────────

st.markdown("---")
st.header("📸 Upload Receipt (Bulk Entry)")
st.caption("Upload a receipt image and extract items with AI")
try:
    gemini_api_key = st.secrets.get("google", {}).get("gemini_api_key", "").strip()
except Exception:
    gemini_api_key = ""
if not gemini_api_key:
    st.info("Receipt OCR is disabled in demo mode. Add a Gemini API key in the app secrets to enable it.")

receipt_who = st.selectbox(
    "Who paid?",
    list(CONFIG.people),
    key="receipt_who"
)

uploaded_file = st.file_uploader(
    "Upload receipt image",
    type=["jpg", "jpeg", "png"],
    key="receipt_upload"
)

if uploaded_file is not None:
    col_img, col_info = st.columns([1, 2])
    with col_img:
        st.image(uploaded_file, width=200)
    with col_info:
        st.write(f"**File:** {uploaded_file.name}")
        st.write(f"**Payer:** {receipt_who}")

    if st.button("🔍 Process receipt with AI", key="process_receipt", type="primary"):
        if not gemini_api_key:
            st.info("Receipt OCR is disabled in demo mode. Add a Gemini API key in the app secrets to enable it.")
            st.stop()
        try:
            from google import genai
        except ImportError:
            st.error("The 'google-genai' package is not installed.")
            st.stop()
        from PIL import Image

        RECEIPT_PROMPT = """
Extract all items from this receipt and return ONLY a valid JSON array (no markdown, no explanation, no ```json wrapper).

For each item, provide:
- date: "YYYY-MM-DD" (from receipt, or use today's date if not visible)
- shop: shop name from receipt
- item: item description from receipt
- category: choose ONE from [groceries, household, eating_out, transport, housing, personal, documents, shopping, health, finance]
- subcategory: choose appropriate subcategory based on item and category
- price: original price as float
- discount: discount amount as float (0 if none)
- final_price: final price after discount as float

Available categories and subcategories:
- groceries: fruits, vegetables, meat, fish, dairy, bakery, drinks, alcohol, snacks, pantry, sweets, coffee_tea, packaging
- household: hygiene, cleaning, paper_goods, kitchen_supplies, home_tools
- eating_out: restaurant, fast_food, cafe, bar_drinks, date
- transport: fuel, parking, public_transport, toll_vignette, uber
- housing: rent, utilities, house_fees, insurance_home
- personal: clothing, shoes, accessories, beauty_cosmetics, hairdresser, sports_fitness, hobbies, subscriptions, gifts
- documents: registrations, official_fees, printing, other_docs
- shopping: electronics, home_decor, furniture, office_supplies, kitchen_equipment
- health: pharmacy, medicine, doctor, insurance_health
- finance: bank_fees, interest, investments

Return ONLY the JSON array, nothing else.
"""

        try:
            with st.spinner("🤖 Analysing receipt with Gemini Vision..."):
                image = Image.open(uploaded_file)
                client = genai.Client(api_key=gemini_api_key)
                response = client.models.generate_content(
                    model="models/gemini-2.0-flash-lite",
                    contents=[RECEIPT_PROMPT, image],
                )
                raw_text = (response.text or "").strip()

            # Strip markdown code fences if present
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
                raw_text = raw_text.strip()

            try:
                items = json.loads(raw_text)
                receipt_df = pd.DataFrame(items)

                # Validate required columns
                required_cols = ["date", "shop", "item", "category", "subcategory",
                                 "price", "discount", "final_price"]
                missing = [c for c in required_cols if c not in receipt_df.columns]
                if missing:
                    st.error(f"Missing columns in parsed data: {missing}")
                else:
                    # Add who and split
                    receipt_df["who"] = receipt_who
                    receipt_df["split"] = "yes"

                    # Coerce types
                    receipt_df["date"] = pd.to_datetime(receipt_df["date"])
                    for col in ["price", "discount", "final_price"]:
                        receipt_df[col] = pd.to_numeric(receipt_df[col], errors="coerce").fillna(0.0)

                    st.session_state["receipt_df"] = receipt_df
                    st.success(f"✅ Found {len(receipt_df)} items. Review below and save.")

            except json.JSONDecodeError as parse_err:
                st.error(f"Could not parse JSON from Gemini response: {parse_err}")
                st.error(f"Raw response:\n{raw_text}")

        except Exception as api_err:
            st.error(f"Gemini API error: {api_err}")

# Show editable table and save button if we have processed receipt data
if "receipt_df" in st.session_state and st.session_state["receipt_df"] is not None:
    receipt_df = st.session_state["receipt_df"]

    st.write("**Review and edit items before saving:**")
    edited_df = st.data_editor(
        receipt_df,
        num_rows="dynamic",
        column_config={
            "date": st.column_config.DateColumn("Date"),
            "price": st.column_config.NumberColumn("Price", format="%.2f"),
            "discount": st.column_config.NumberColumn("Discount", format="%.2f"),
            "final_price": st.column_config.NumberColumn("Final Price", format="%.2f"),
        },
        key="receipt_editor"
    )

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("💾 Save all to Google Sheets", key="save_receipt", type="primary", use_container_width=True):
            try:
                # Load current sheet data
                worksheet = sh.worksheet(selected_worksheet)
                existing_data = worksheet.get_all_records()
                existing_df = pd.DataFrame(existing_data)

                # Normalise column names to match the sheet (Title Case)
                col_rename = {
                    "date": "Date", "shop": "Shop", "item": "Item",
                    "category": "Category", "subcategory": "Subcategory",
                    "price": "Price", "discount": "Discount",
                    "final_price": "Final_Price", "who": "Who", "split": "Split"
                }
                save_df = edited_df.rename(columns=col_rename)
                save_df["Date"] = pd.to_datetime(save_df["Date"]).dt.strftime("%Y-%m-%d")
                save_df["Exclude_Balance"] = "no"
                save_df = ensure_balance_columns(save_df)
                existing_df = ensure_balance_columns(existing_df)

                updated_df = pd.concat([existing_df, save_df], ignore_index=True)
                conn.update(worksheet=selected_worksheet, data=updated_df)
                st.cache_data.clear()

                count = len(edited_df)
                st.session_state["receipt_df"] = None
                st.success(f"✅ {count} item(s) saved to {selected_worksheet}!")
                st.rerun()

            except Exception as save_err:
                st.error(f"Error saving to Google Sheets: {save_err}")

    with col_cancel:
        if st.button("❌ Cancel", use_container_width=True):
            st.session_state["receipt_df"] = None
            st.rerun()

st.markdown("---")

# ────────────────────────────────────────────────────────────────────────────
# SECTION 2: Manual Entry
# ────────────────────────────────────────────────────────────────────────────

st.header("✏️ Manual Entry")
st.caption("Add a single expense manually")

# Category to subcategory mapping
CATEGORY_TO_SUBCATEGORIES = {
    "groceries": [
        "fruits", "vegetables", "meat", "fish", "dairy",
        "bakery", "drinks", "alcohol", "snacks",
        "pantry", "sweets", "coffee_tea", "packaging"
    ],
    "household": ["hygiene", "cleaning", "paper_goods", "kitchen_supplies", "home_tools"],
    "eating_out": ["restaurant", "fast_food", "cafe", "bar_drinks", "date"],
    "transport": ["fuel", "parking", "public_transport", "toll_vignette", "uber"],
    "housing": ["rent", "utilities", "house_fees", "insurance_home"],
    "personal": [
        "clothing", "shoes", "accessories", "beauty_cosmetics",
        "hairdresser", "sports_fitness", "hobbies",
        "subscriptions", "gifts",
    ],
    "documents": ["registrations", "official_fees", "printing", "other_docs"],
    "shopping": ["electronics", "home_decor", "furniture", "office_supplies", "kitchen_equipment"],
    "health": ["pharmacy", "medicine", "doctor", "insurance_health"],
    "finance": ["bank_fees", "interest", "investments"],
}

# Category and subcategory selectors (outside form, with session state)
col_cat, col_subcat = st.columns(2)

with col_cat:
    selected_category = st.selectbox(
        "Category",
        list(CATEGORY_TO_SUBCATEGORIES.keys()),
        key="manual_category"
    )

with col_subcat:
    subcategories = CATEGORY_TO_SUBCATEGORIES.get(selected_category, [])
    selected_subcategory = st.selectbox(
        "Subcategory",
        subcategories,
        key="manual_subcategory"
    )

# Manual entry form
with st.form("manual_expense_form", clear_on_submit=True):
    col1, col2, col3 = st.columns(3)
    
    with col1:
        expense_date = st.date_input("Date", value=dt.date.today())
    
    with col2:
        expense_who = st.selectbox("Who paid?", list(CONFIG.people), key="manual_who")
    
    with col3:
        is_split = st.checkbox("Split expense?", value=False, key="manual_split")

    if is_split:
        exclude_balance = st.checkbox(
            "Exclude from balance calculation",
            value=False,
            key="manual_exclude_balance",
            help="Use for pre-settled expenses like rent",
        )
        st.caption("Use for pre-settled expenses like rent")
    else:
        exclude_balance = False
        st.session_state["manual_exclude_balance"] = False

    expense_shop = st.text_input("Shop/Vendor", placeholder="e.g., Lidl, Restaurant Name")
    expense_item = st.text_input("Item description", placeholder="e.g., Weekly groceries")

    col_price, col_discount, col_final = st.columns(3)
    
    with col_price:
        expense_price = st.number_input("Price (€)", min_value=0.0, step=0.01)
    
    with col_discount:
        expense_discount = st.number_input("Discount (€)", min_value=0.0, step=0.01)
    
    with col_final:
        final_price = expense_price - expense_discount
        st.metric("Final Price", f"€{final_price:.2f}")

    submitted = st.form_submit_button("✅ Save Expense", type="primary", use_container_width=True)

    if submitted and expense_shop and expense_item and final_price > 0:
        try:
            if sh is None or conn is None:
                st.warning("Saving is unavailable in demo mode. Configure Google Sheets first.")
                st.stop()
            # Create new expense row
            new_expense = {
                "Date": expense_date.strftime("%Y-%m-%d"),
                "Shop": expense_shop,
                "Item": expense_item,
                "Category": selected_category,
                "Subcategory": selected_subcategory,
                "Price": expense_price,
                "Discount": expense_discount,
                "Final_Price": final_price,
                "Who": expense_who,
                "Split": "yes" if is_split else "no",
                "Exclude_Balance": "yes" if (is_split and exclude_balance) else "no"
            }

            # Load current sheet data and append
            worksheet = sh.worksheet(selected_worksheet)
            existing_data = worksheet.get_all_records()
            existing_df = pd.DataFrame(existing_data)
            existing_df = ensure_balance_columns(existing_df)

            # Convert existing data to proper types
            for col in ["Price", "Discount", "Final_Price"]:
                if col in existing_df.columns:
                    existing_df[col] = pd.to_numeric(existing_df[col], errors="coerce")

            # Append new expense
            new_df = pd.concat(
                [existing_df, ensure_balance_columns(pd.DataFrame([new_expense]))],
                ignore_index=True
            )

            # Update Google Sheets
            conn.update(worksheet=selected_worksheet, data=new_df)
            st.cache_data.clear()

            st.success(f"✅ Expense saved to {selected_worksheet}!")
            st.rerun()

        except Exception as e:
            st.error(f"Error saving expense: {e}")

    elif submitted:
        st.warning("⚠️ Please fill in all required fields (Shop, Item, Price > 0)")
