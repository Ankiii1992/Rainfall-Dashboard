import streamlit as st
import pandas as pd
import plotly.express as px
import gspread
from google.oauth2.service_account import Credentials

# --- Streamlit page settings ---
st.set_page_config(page_title="Rainfall Dashboard", layout="wide")

# --- Enhanced CSS ---
st.markdown("""
<style>
    html, body, .main {
        background-color: #f3f6fa;
        font-family: 'Segoe UI', sans-serif;
    }
    .title-text {
        font-size: 2.8rem;
        font-weight: 800;
        color: #1a237e;
        padding: 1rem 0 0.2rem 0;
    }
    .metric-container {
        padding: 0.8rem;
    }
    .metric-tile {
        background: linear-gradient(135deg, #f0faff, #e0f2f1);
        padding: 1.2rem 1.4rem 1rem 1.4rem;
        border-radius: 1.25rem;
        box-shadow: 0 6px 16px rgba(0, 0, 0, 0.06);
        text-align: center;
        transition: 0.3s ease;
        border: 1px solid #c5e1e9;
        height: 165px;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    .metric-tile:hover {
        transform: translateY(-4px);
        box-shadow: 0 10px 28px rgba(0, 0, 0, 0.1);
    }
    .metric-tile h4 {
        color: #01579b;
        font-size: 1.05rem;
        margin-bottom: 0.2rem;
    }
    .metric-tile h2 {
        font-size: 2.2rem;
        color: #0077b6;
        margin: 0.1rem 0 0.1rem 0;
        font-weight: 700;
    }
    .metric-tile p {
        margin: 0 0 0;
        font-size: 0.95rem;
        color: #37474f;
    }
</style>
""", unsafe_allow_html=True)

@st.cache_data
def load_all_sheet_tabs():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)
    spreadsheet = client.open("Rainfall Dashboard")
    sheet_tabs = spreadsheet.worksheets()

    data_by_date = {}
    for tab in sheet_tabs:
        tab_name = tab.title
        data = tab.get_all_values()
        if not data or len(data) < 2:
            continue

        df = pd.DataFrame(data[1:], columns=data[0])
        df.replace("", pd.NA, inplace=True)
        df = df.dropna(how="all")
        df.columns = df.columns.str.strip()

        df.rename(columns={"DISTRICT": "District", "TALUKA": "Taluka", "TOTAL": "Total_mm"}, inplace=True)

        if "Total_mm" in df.columns:
            df["Total_mm"] = pd.to_numeric(df["Total_mm"], errors="coerce")

        for col in df.columns:
            if "TO" in col:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        data_by_date[tab_name] = df

    return data_by_date

# --- Load data ---
data_by_date = load_all_sheet_tabs()
available_dates = sorted(data_by_date.keys(), reverse=True)
st.markdown("<div class='title-text'>🌧️ Gujarat Rainfall Dashboard</div>", unsafe_allow_html=True)

selected_tab = st.selectbox("📅 Select Date", available_dates, index=0)

df = data_by_date[selected_tab]
df.columns = df.columns.str.strip()

time_slot_columns = [col for col in df.columns if "TO" in col]

df_long = df.melt(
    id_vars=["District", "Taluka", "Total_mm"],
    value_vars=time_slot_columns,
    var_name="Time Slot",
    value_name="Rainfall (mm)"
)
df_long = df_long.dropna(subset=["Rainfall (mm)"])
df_long = df_long.sort_values(by=["Taluka", "Time Slot"])

# --- Metrics ---
top_taluka_row = df.sort_values(by='Total_mm', ascending=False).iloc[0]
df_latest = df_long[df_long['Time Slot'] == df_long['Time Slot'].max()]
top_latest = df_latest.sort_values(by='Rainfall (mm)', ascending=False).iloc[0]
num_talukas_with_rain = df[df['Total_mm'] > 0].shape[0]
more_than_150 = df[df['Total_mm'] > 150].shape[0]
more_than_100 = df[df['Total_mm'] > 100].shape[0]
more_than_50 = df[df['Total_mm'] > 50].shape[0]

# --- Format Time Slot ---
def format_time_slot(slot):
    if "TO" in slot:
        start, end = slot[:2], slot[-2:]
        return f"{int(start)}-{int(end)}"
    return slot

df_long["Display Slot"] = df_long["Time Slot"].apply(format_time_slot)

# --- Metric Tiles ---
st.markdown("### Overview")
row1 = st.columns(3)
row2 = st.columns(3)

row1_titles = [
    ("Total Talukas with Rainfall", num_talukas_with_rain),
    ("Highest Rainfall Total", f"{top_taluka_row['Taluka']}<br><p>{top_taluka_row['Total_mm']} mm</p>"),
    ("Highest Rainfall in Last 2 Hours", f"{top_latest['Taluka']}<br><p>{top_latest['Rainfall (mm)']} mm</p>")
]

row2_titles = [
    ("Talukas > 150 mm", more_than_150),
    ("Talukas > 100 mm", more_than_100),
    ("Talukas > 50 mm", more_than_50)
]

for col, (label, value) in zip(row1, row1_titles):
    with col:
        st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-tile'><h4>{label}</h4><h2>{value}</h2></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

for col, (label, value) in zip(row2, row2_titles):
    with col:
        st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-tile'><h4>{label}</h4><h2>{value}</h2></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

# --- Chart ---
st.markdown("### 📈 Rainfall Trend by Time Slot")
selected_talukas = st.multiselect("Select Taluka(s)", sorted(df_long['Taluka'].unique()), default=[top_taluka_row['Taluka']])

if selected_talukas:
    plot_df = df_long[df_long['Taluka'].isin(selected_talukas)]
    fig = px.line(plot_df, x="Display Slot", y="Rainfall (mm)", color="Taluka", markers=True,
                  title="Rainfall Trend Over Time", labels={"Rainfall (mm)": "Rainfall (mm)"})
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

# --- Table ---
st.markdown("### 📋 Full Rainfall Data Table")
st.table(df.sort_values(by="Total_mm", ascending=False).reset_index(drop=True))
