import streamlit as st
import pandas as pd
import datetime as dt

#import analysis functions
from analysis import (
    total_spent, spent_by_category, spent_by_subcategory,
    spent_by_person, spent_by_shop
)
from data_loader import load_month
from config import require_access

#category mapping
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

st.set_page_config(page_title="Expense Analysis", page_icon="📈")
require_access()

# Page title
st.title("📈 Detailed Analysis")

# Get selected month from session state (set by home page), fallback to current
if "selected_worksheet" in st.session_state:
    selected_worksheet = st.session_state["selected_worksheet"]
else:
    # Fallback to current month
    today = dt.date.today()
    selected_worksheet = today.strftime("%Y_%m")

df = load_month(selected_worksheet)
if df.empty:
    st.warning(f"No data found for {selected_worksheet}. Select a month from home page.")
    st.stop()
df = df.sort_values("Date", ascending=False)

# Display current month
st.caption(f"📅 Showing data for: **{selected_worksheet}**")

#by category & subcategory
col1, col2 = st.columns(2)

with col1:
    st.subheader("By category")
    by_cat = spent_by_category(df)
    st.dataframe(by_cat.rename("EUR"))
    st.bar_chart(by_cat)

with col2:
    st.subheader("By subcategory")
    by_subcat = spent_by_subcategory(df)
    st.dataframe(by_subcat.rename("EUR"))
    st.bar_chart(by_subcat)

# Discount analysis for groceries & household
st.markdown("---")
st.subheader("💰 Discount savings (Groceries & Household)")

# Filter for groceries and household categories
discount_categories = ["groceries", "household"]
df_discount = df[df["Category"].isin(discount_categories)].copy()

if not df_discount.empty and "Discount" in df_discount.columns:
    # Calculate metrics
    total_discount = df_discount["Discount"].sum()
    items_with_discount = (df_discount["Discount"] > 0).sum()
    
    # Calculate average discount percentage (only for items with discount)
    df_with_discount = df_discount[df_discount["Discount"] > 0]
    if not df_with_discount.empty and "Price" in df_with_discount.columns:
        avg_discount_pct = (df_with_discount["Discount"] / df_with_discount["Price"] * 100).mean()
    else:
        avg_discount_pct = 0.0
    
    # Display metrics
    metric_col1, metric_col2, metric_col3 = st.columns(3)
    with metric_col1:
        st.metric("Total saved", f"{total_discount:.2f} EUR")
    with metric_col2:
        st.metric("Avg discount %", f"{avg_discount_pct:.1f}%")
    with metric_col3:
        st.metric("Items with discount", items_with_discount)
    
    # Expandable details
    with st.expander("📊 View discount details"):
        # Breakdown by category
        st.write("**Savings by category:**")
        discount_by_cat = df_discount.groupby("Category").agg(
            **{"Total saved": pd.NamedAgg(column="Discount", aggfunc="sum"),
               "Items": pd.NamedAgg(column="Discount", aggfunc="count")}
        ).sort_values("Total saved", ascending=False)
        st.dataframe(discount_by_cat.style.format({"Total saved": "{:.2f}"}))
        
        # Top discounted items
        if not df_with_discount.empty:
            st.write("**Top 5 discounted items:**")
            top_discounts = df_with_discount.nlargest(5, "Discount")[
                ["Date", "Shop", "Item", "Category", "Price", "Discount", "Final_Price"]
            ].copy()
            top_discounts["Discount %"] = (top_discounts["Discount"] / top_discounts["Price"] * 100).round(1)
            st.dataframe(
                top_discounts.style.format({
                    "Price": "{:.2f}",
                    "Discount": "{:.2f}",
                    "Final_Price": "{:.2f}",
                    "Discount %": "{:.1f}%"
                })
            )
else:
    st.info("No discount data available for groceries and household categories.")

#by person & shop
col3, col4 = st.columns(2)

with col3:
    st.subheader("By person (who paid)")
    by_person = spent_by_person(df)
    st.dataframe(by_person.rename("EUR"))
    st.bar_chart(by_person)

with col4:
    st.subheader("By shop")
    by_shop = spent_by_shop(df)
    st.dataframe(by_shop.rename("EUR"))
    st.bar_chart(by_shop)

st.markdown("---")

#raw data table
with st.expander("Show raw data"):
    st.dataframe(df)
