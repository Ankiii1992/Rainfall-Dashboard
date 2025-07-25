import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import calendar

# --- Google Drive Setup ---

@st.cache_resource
def get_gsheet_client():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)
    return client
    
def load_sheet_data(base_folder, year, month, sheet_name, tab_name):
    try:
        folder_path = f"{base_folder}/{year}/{month}"
        spreadsheet = client.open(sheet_name)
        worksheet = spreadsheet.worksheet(tab_name)
        data = worksheet.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"❌ Failed to load data: {e}")
        return pd.DataFrame()

# --- Tiles for 24 Hourly Rainfall ---
def show_24_hourly_dashboard(df):
    st.subheader("📊 24 Hourly Rainfall Summary")

    df["Rain_Last_24_Hrs"] = pd.to_numeric(df["Rain_Last_24_Hrs"], errors='coerce')
    df = df.dropna(subset=["Rain_Last_24_Hrs"])

    state_avg = df["Rain_Last_24_Hrs"].mean()

    max_row = df.loc[df["Rain_Last_24_Hrs"].idxmax()]
    max_taluka_name = f"{max_row['Taluka']} ({max_row['District']})"
    max_rain = max_row["Rain_Last_24_Hrs"]

    district_avg_df = df.groupby("District")["Rain_Last_24_Hrs"].mean().reset_index()
    top_district_row = district_avg_df.loc[district_avg_df["Rain_Last_24_Hrs"].idxmax()]
    top_district = top_district_row["District"]
    top_district_avg = top_district_row["Rain_Last_24_Hrs"]

    above_avg_count = (df["Rain_Last_24_Hrs"] > state_avg).sum()
    total_talukas = len(df)
    percent_above = (above_avg_count / total_talukas) * 100

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("🌧️ State Avg Rainfall", f"{state_avg:.1f} mm")

    with col2:
        st.metric("🌧️ Max Rainfall (Taluka)", max_taluka_name, f"{max_rain:.1f} mm")

    with col3:
        st.metric("🏞️ Top District (Avg)", top_district, f"{top_district_avg:.1f} mm")

    with col4:
        st.metric("📈 Talukas > State Avg", f"{percent_above:.1f}%", f"{above_avg_count} / {total_talukas}")

    st.dataframe(df)

# --- Main Streamlit App ---
client = get_gsheet_client()
st.set_page_config(page_title="Rainfall Dashboard", layout="wide")
st.title("☁️ Gujarat Rainfall Dashboard")

# --- UI Controls ---
data_type = st.radio("Select Data Type", ["2 Hourly Rainfall", "24 Hourly Rainfall"], index=0)

today = datetime.today()
years = list(range(2023, today.year + 1))
months = list(calendar.month_name)[1:]  # Skips empty first entry
selected_year = st.selectbox("Select Year", years, index=years.index(today.year))
selected_month = st.selectbox("Select Month", months, index=today.month - 1)

# Get number of days in selected month
days_in_month = calendar.monthrange(selected_year, months.index(selected_month)+1)[1]
selected_day = st.selectbox("Select Day", list(range(1, days_in_month + 1)), index=today.day - 1)

selected_date = datetime(selected_year, months.index(selected_month)+1, selected_day).strftime("%Y-%m-%d")

# --- Sheet File Setup ---
if data_type == "24 Hourly Rainfall":
    folder_name = "Rainfall Dashboard/24 Hourly Sheets"
    sheet_name = f"24HR_Rainfall_{selected_month}_{selected_year}"
    tab_name = f"master24hrs_{selected_date}"

    df = load_sheet_data(folder_name, selected_year, selected_month, sheet_name, tab_name)

    if not df.empty:
        show_24_hourly_dashboard(df)
    else:
        st.warning("⚠️ No data available for this date.")

elif data_type == "2 Hourly Rainfall":
    folder_name = "Rainfall Dashboard/2 Hourly Sheets"
    sheet_name = f"2HR_Rainfall_{selected_month}_{selected_year}"
    tab_name = f"master2hrs_{selected_date}"

    df = load_sheet_data(folder_name, selected_year, selected_month, sheet_name, tab_name)

    if not df.empty:
        st.subheader("📊 2 Hourly Rainfall Data")
        st.dataframe(df)
    else:
        st.warning("⚠️ No data available for this date.")
