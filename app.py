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

# --- Updated CSS (Freepik-style card tiles) ---
st.markdown("""
<style>
    html, body, .main {
        background-color: #f4f7fb;
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
        background: #ffffff;
        padding: 1.5rem;
        border-radius: 1.5rem;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06);
        text-align: center;
        border: 1px solid #e0e0e0;
    }
    .metric-tile h4 {
        color: #6c757d;
        font-size: 1.2rem;
        font-weight: 600;
    }
    .metric-tile h2 {
        font-size: 2.6rem;
        color: #222;
        font-weight: 800;
        margin: 0.5rem 0 0.2rem 0;
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
available_dates = sorted(
    data_by_date.keys(),
    key=lambda d: datetime.strptime(d, "%d-%m-%Y"),
    reverse=True
)

st.markdown("<div class='title-text'>\ud83c\udf27\ufe0f Gujarat Rainfall Dashboard</div>", unsafe_allow_html=True)

selected_tab = st.selectbox("\ud83d\uddd5\ufe0f Select Date", available_dates, index=0)
df = data_by_date[selected_tab]
df.columns = df.columns.str.strip()

time_slot_columns = [col for col in df.columns if "TO" in col]
time_slot_order = ['06TO08', '08TO10', '10TO12', '12TO14', '14TO16', '16TO18',
                   '18TO20', '20TO22', '22TO24', '24TO02', '02TO04', '04TO06']
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
    "04TO06": "4–6 AM",
}

# Melt and clean data
df_long = df.melt(
    id_vars=["District", "Taluka", "Total_mm"],
    value_vars=existing_order,
    var_name="Time Slot",
    value_name="Rainfall (mm)"
)
df_long = df_long.dropna(subset=["Rainfall (mm)"])
df_long['Taluka'] = df_long['Taluka'].str.strip()
df_long = df_long.groupby(["District", "Taluka", "Time Slot"], as_index=False).agg({
    "Rainfall (mm)": "sum",
    "Total_mm": "first"
})

df_long['Time Slot Label'] = pd.Categorical(
    df_long['Time Slot'].map(slot_labels),
    categories=[slot_labels[slot] for slot in existing_order],
    ordered=True
)
df_long = df_long.sort_values(by=["Taluka", "Time Slot Label"])

# --- Metrics ---
top_taluka_row = df.sort_values(by='Total_mm', ascending=False).iloc[0]
df_latest_slot = df_long[df_long['Time Slot'] == existing_order[-1]]
top_latest = df_latest_slot.sort_values(by='Rainfall (mm)', ascending=False).iloc[0]

num_talukas_with_rain = df[df['Total_mm'] > 0].shape[0]
more_than_150 = df[df['Total_mm'] > 150].shape[0]
more_than_100 = df[df['Total_mm'] > 100].shape[0]
more_than_50 = df[df['Total_mm'] > 50].shape[0]

last_slot_label = slot_labels[existing_order[-1]]

st.markdown(f"#### \ud83d\udcca Latest data available for time slot: **{last_slot_label}**")
st.markdown("### Overview")

# --- Enhanced Tiles Section ---
row1 = st.columns(3)
with row1[0]:
    st.markdown("<div class='metric-container'><div class='metric-tile'>", unsafe_allow_html=True)
    st.markdown(f"<h4>Total Talukas with Rainfall</h4><h2>{num_talukas_with_rain}</h2>", unsafe_allow_html=True)
    st.markdown("</div></div>", unsafe_allow_html=True)

with row1[1]:
    st.markdown("<div class='metric-container'><div class='metric-tile'>", unsafe_allow_html=True)
    st.markdown(f"<h4>Highest Rainfall Total</h4><h2>{top_taluka_row['Taluka']}<br><p>{top_taluka_row['Total_mm']} mm</p></h2>", unsafe_allow_html=True)
    st.markdown("</div></div>", unsafe_allow_html=True)

with row1[2]:
    st.markdown("<div class='metric-container'><div class='metric-tile'>", unsafe_allow_html=True)
    st.markdown(f"<h4>Highest Rainfall in Last 2 Hours ({last_slot_label})</h4><h2>{top_latest['Taluka']}<br><p>{top_latest['Rainfall (mm)']} mm</p></h2>", unsafe_allow_html=True)
    st.markdown("</div></div>", unsafe_allow_html=True)

st.markdown("<div style='margin-bottom: 1.5rem;'></div>", unsafe_allow_html=True)

row2 = st.columns(3)
with row2[0]:
    st.markdown("<div class='metric-container'><div class='metric-tile'>", unsafe_allow_html=True)
    st.markdown(f"<h4>Talukas > 150 mm</h4><h2>{more_than_150}</h2>", unsafe_allow_html=True)
    st.markdown("</div></div>", unsafe_allow_html=True)

with row2[1]:
    st.markdown("<div class='metric-container'><div class='metric-tile'>", unsafe_allow_html=True)
    st.markdown(f"<h4>Talukas > 100 mm</h4><h2>{more_than_100}</h2>", unsafe_allow_html=True)
    st.markdown("</div></div>", unsafe_allow_html=True)

with row2[2]:
    st.markdown("<div class='metric-container'><div class='metric-tile'>", unsafe_allow_html=True)
    st.markdown(f"<h4>Talukas > 50 mm</h4><h2>{more_than_50}</h2>", unsafe_allow_html=True)
    st.markdown("</div></div>", unsafe_allow_html=True)

# --- Chart Section ---
st.markdown("### \ud83d\udcc8 Rainfall Trend by Time Slot")
selected_talukas = st.multiselect("Select Taluka(s)", sorted(df_long['Taluka'].unique()), default=[top_taluka_row['Taluka']])

if selected_talukas:
    plot_df = df_long[df_long['Taluka'].isin(selected_talukas)]
    fig = px.line(
        plot_df,
        x="Time Slot Label",
        y="Rainfall (mm)",
        color="Taluka",
        markers=True,
        text="Rainfall (mm)",
        title="Rainfall Trend Over Time",
        labels={"Rainfall (mm)": "Rainfall (mm)"}
    )
    fig.update_traces(textposition="top center")
    fig.update_layout(showlegend=True)
    fig.update_layout(modebar_remove=['toImage'])
    st.plotly_chart(fig, use_container_width=True)

# --- Choropleth Map Section ---
st.markdown("### \ud83d\uddfd\ufe0f Gujarat Rainfall Map (by Taluka)")

if os.path.exists("gujarat_taluka_clean.geojson"):
    with open("gujarat_taluka_clean.geojson", "r", encoding="utf-8") as f:
        taluka_geojson = json.load(f)
    st.success(f"\u2705 GeoJSON loaded — {len(taluka_geojson['features'])} features found.")

    for feature in taluka_geojson["features"]:
        feature["properties"]["SUB_DISTRICT"] = feature["properties"]["SUB_DISTRICT"].strip().lower()

    df_map = df.copy()
    df_map["Taluka"] = df_map["Taluka"].str.strip().str.lower()

    def classify_rainfall(mm):
        if mm <= 10: return "Very Low"
        elif mm <= 25: return "Low"
        elif mm <= 50: return "Moderate"
        elif mm <= 100: return "Heavy"
        elif mm <= 150: return "Very Heavy"
        elif mm <= 200: return "Intense"
        elif mm <= 300: return "Extreme"
        else: return "Exceptional"

    df_map["Rainfall Category"] = df_map["Total_mm"].apply(classify_rainfall)

    color_map = {
        "Very Low": "#cceeff",
        "Low": "#66ffcc",
        "Moderate": "#33cc33",
        "Heavy": "#ffff66",
        "Very Heavy": "#ff9933",
        "Intense": "#ff3333",
        "Extreme": "#ff66cc",
        "Exceptional": "#9900cc"
    }

    fig = px.choropleth_mapbox(
        df_map,
        geojson=taluka_geojson,
        featureidkey="properties.SUB_DISTRICT",
        locations="Taluka",
        color="Rainfall Category",
        color_discrete_map=color_map,
        mapbox_style="open-street-map",
        center={"lat": 22.5, "lon": 71.5},
        zoom=6,
        opacity=0.75,
        height=650,
        hover_name="Taluka",
        hover_data=["District", "Total_mm"]
    )
    fig.update_layout(margin={"r": 0, "t": 0, "l": 0, "b": 0})
    st.plotly_chart(fig, use_container_width=True)

else:
    st.error("\u274c GeoJSON file not found.")

# --- Table Section ---
st.markdown("### \ud83d\udccb Full Rainfall Data Table")
df_display = df.sort_values(by="Total_mm", ascending=False).reset_index(drop=True)
df_display.index += 1
st.dataframe(df_display, use_container_width=True, height=600)
