import streamlit as st
import pandas as pd
import plotly.express as px
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import json
import os

# --- Streamlit page settings ---
st.set_page_config(page_title="Rainfall Dashboard", layout="wide")

# --- Global CSS + Disable Right Click ---
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
    .metric-tile {
        background: linear-gradient(135deg, #f0faff, #e0f2f1);
        padding: 1.2rem 1.4rem 1rem 1.4rem;
        border-radius: 1.25rem;
        box-shadow: 0 6px 16px rgba(0,0,0,0.06);
        text-align: center;
        height: 165px;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
</style>
<script>
    document.addEventListener('contextmenu', event => event.preventDefault());
</script>
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
        data = tab.get_all_values()
        if not data or len(data) < 2:
            continue
        df = pd.DataFrame(data[1:], columns=data[0])
        df.columns = df.columns.str.strip()
        df.rename(columns={"DISTRICT": "District", "TALUKA": "Taluka", "TOTAL": "Total_mm"}, inplace=True)
        df.replace("", pd.NA, inplace=True)
        df = df.dropna(how="all")

        if "Total_mm" in df.columns:
            df["Total_mm"] = pd.to_numeric(df["Total_mm"], errors="coerce")
        for col in df.columns:
            if "TO" in col:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        data_by_date[tab.title] = df
    return data_by_date

@st.cache_resource
def load_geojson():
    if os.path.exists("gujarat_taluka_clean.geojson"):
        with open("gujarat_taluka_clean.geojson", "r", encoding="utf-8") as f:
            return json.load(f)
    return None

# --- Rainfall Category & Color Mapping ---
category_colors = {
    "Very Light": "#c8e6c9",
    "Light": "#00ff01",
    "Moderate": "#ffff00",
    "Rather Heavy": "#ffa500",
    "Heavy": "#d61a1c",
    "Very Heavy": "#3b0030",
    "Extremely Heavy": "#4c0073",
    "Exceptional": "#ffdbff"
}

category_ranges = {
    "Very Light": "0.1 – 2.4 mm",
    "Light": "2.5 – 7.5 mm",
    "Moderate": "7.6 – 35.5 mm",
    "Rather Heavy": "35.6 – 64.4 mm",
    "Heavy": "64.5 – 124.4 mm",
    "Very Heavy": "124.5 – 244.4 mm",
    "Extremely Heavy": "244.5 – 350 mm",
    "Exceptional": "> 350 mm"
}

def categorize(rainfall):
    if rainfall <= 2.4:
        return "Very Light"
    elif rainfall <= 7.5:
        return "Light"
    elif rainfall <= 35.5:
        return "Moderate"
    elif rainfall <= 64.4:
        return "Rather Heavy"
    elif rainfall <= 124.4:
        return "Heavy"
    elif rainfall <= 244.4:
        return "Very Heavy"
    elif rainfall <= 350:
        return "Extremely Heavy"
    else:
        return "Exceptional"

# --- Load Data ---
data_by_date = load_all_sheet_tabs()
available_dates = sorted(data_by_date.keys(), key=lambda d: datetime.strptime(d, "%d-%m-%Y"), reverse=True)

st.markdown("<div class='title-text'>🌧️ Gujarat Rainfall Dashboard</div>", unsafe_allow_html=True)

selected_tab = st.selectbox("🗕️ Select Date", available_dates, index=0)
df = data_by_date[selected_tab]

time_slot_columns = [col for col in df.columns if "TO" in col]
time_slot_order = ['06TO08', '08TO10', '10TO12', '12TO14', '14TO16', '16TO18', '18TO20', '20TO22', '22TO24', '24TO02', '02TO04', '04TO06']
existing_order = [slot for slot in time_slot_order if slot in time_slot_columns]

slot_labels = {
    "06TO08": "6–8 AM",
    "08TO10": "8–10 AM",
    "10TO12": "10–12 AM",
    "12TO14": "12–2 PM",
    "14TO16": "2–4 PM",
    "16TO18": "4–6 PM",
    "18TO20": "6–8 PM",
    "20TO22": "8–10 PM",
    "22TO24": "10–12 PM",
    "24TO02": "12–2 AM",
    "02TO04": "2–4 AM",
    "04TO06": "4–6 AM"
}

df_long = df.melt(id_vars=["District", "Taluka", "Total_mm"], value_vars=existing_order, var_name="Time Slot", value_name="Rainfall (mm)").dropna()
df_long['Time Slot Label'] = pd.Categorical(df_long['Time Slot'].map(slot_labels), categories=[slot_labels[s] for s in existing_order], ordered=True)
df_long = df_long.sort_values(by=["Taluka", "Time Slot Label"])

top_taluka = df.sort_values("Total_mm", ascending=False).iloc[0]
latest_slot = df_long[df_long["Time Slot"] == existing_order[-1]].sort_values("Rainfall (mm)", ascending=False).iloc[0]

st.markdown("### Overview")
cols = st.columns(3)
cols[0].markdown(f"<div class='metric-tile'><h4>Total Talukas with Rainfall</h4><h2>{df[df['Total_mm'] > 0].shape[0]}</h2></div>", unsafe_allow_html=True)
cols[1].markdown(f"<div class='metric-tile'><h4>Highest Rainfall Total</h4><h2>{top_taluka['Taluka']}<br>{top_taluka['Total_mm']} mm</h2></div>", unsafe_allow_html=True)
cols[2].markdown(f"<div class='metric-tile'><h4>Highest Rainfall Last Slot</h4><h2>{latest_slot['Taluka']}<br>{latest_slot['Rainfall (mm)']} mm</h2></div>", unsafe_allow_html=True)

st.markdown("### 📈 Rainfall Trend")
selected_talukas = st.multiselect("Select Talukas", sorted(df_long["Taluka"].unique()), default=[top_taluka['Taluka']])
if selected_talukas:
    trend_data = df_long[df_long["Taluka"].isin(selected_talukas)]
    fig = px.line(trend_data, x="Time Slot Label", y="Rainfall (mm)", color="Taluka", markers=True)
    st.plotly_chart(fig, use_container_width=True)

st.markdown("### 🗺️ Gujarat Rainfall Map")
geojson_data = load_geojson()
if geojson_data:
    for f in geojson_data["features"]:
        f["properties"]["SUB_DISTRICT"] = f["properties"]["SUB_DISTRICT"].strip().lower()
    df_map = df.copy()
    df_map["Taluka"] = df_map["Taluka"].str.strip().str.lower()
    df_map["Rainfall Category"] = df_map["Total_mm"].apply(categorize)

    fig = px.choropleth_mapbox(
        df_map,
        geojson=geojson_data,
        featureidkey="properties.SUB_DISTRICT",
        locations="Taluka",
        color="Rainfall Category",
        color_discrete_map=category_colors,
        mapbox_style="open-street-map",
        center={"lat": 22.5, "lon": 71.5},
        zoom=6.2,
        opacity=0.75,
        hover_name="Taluka",
        hover_data=["District", "Total_mm"],
        height=600
    )
    st.plotly_chart(fig, use_container_width=True)

    # Custom Legend
    st.markdown("### Rainfall Categories Legend")
    for cat, color in category_colors.items():
        st.markdown(f"<div style='display: flex; align-items: center; margin-bottom: 5px;'><div style='width: 20px; height: 20px; background-color: {color}; border: 1px solid #000; margin-right: 10px;'></div><strong>{cat}</strong>: {category_ranges[cat]}</div>", unsafe_allow_html=True)
else:
    st.error("GeoJSON data not found.")

st.markdown("### 📋 Full Rainfall Data Table")
df_display = df.sort_values(by="Total_mm", ascending=False).reset_index(drop=True)
df_display.index += 1
st.dataframe(df_display, use_container_width=True, height=600)
