import streamlit as st
import pandas as pd
import plotly.express as px
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import datetime, timedelta
import geopandas as gpd
import plotly.graph_objects as go

# ---------------------------- CONFIG ----------------------------
@st.cache_resource
def get_gsheet_client():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    return gspread.authorize(creds)

# ---------------------------- RAINFALL CATEGORY LOGIC ----------------------------
color_map = {
    "No Rain": "#f8f8f8",
    "Very Light": "#e0ffe0",
    "Light": "#00ff01",
    "Moderate": "#00ffff",
    "Rather Heavy": "#ffeb3b",
    "Heavy": "#ff8c00",
    "Very Heavy": "#d50000",
    "Extremely Heavy": "#f820fe",
    "Exceptional": "#e8aaf5"
}

def classify_rainfall(rainfall):
    if pd.isna(rainfall) or rainfall == 0:
        return "No Rain"
    elif rainfall <= 2.4:
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

# ---------------------------- UTILITY ----------------------------
def generate_title_from_date(selected_date):
    start_date = (selected_date - timedelta(days=1)).strftime("%d-%m-%Y")
    end_date = selected_date.strftime("%d-%m-%Y")
    return f"24 Hours Rainfall Summary ({start_date} 06:00 AM to {end_date} 06:00 AM)"

# ---------------------------- LOAD DATA ----------------------------
def load_worksheet_df(sheet_name, worksheet_name):
    client = get_gsheet_client()
    sheet = client.open(sheet_name).worksheet(worksheet_name)
    df = pd.DataFrame(sheet.get_all_records())
    return df

# ---------------------------- CHOROPLETH ----------------------------
def plot_choropleth(df, geojson_path):
    gdf = gpd.read_file(geojson_path)
    df["Rainfall_Category"] = df["Rain_Last_24_Hrs"].apply(classify_rainfall)

    fig = px.choropleth_mapbox(
        df,
        geojson=gdf.set_index("TALUKA").__geo_interface__,
        locations="Taluka",
        color="Rainfall_Category",
        color_discrete_map=color_map,
        mapbox_style="carto-positron",
        zoom=5.2,
        center={"lat": 22.3, "lon": 71.7},
        opacity=0.7,
        hover_name="Taluka",
        hover_data={"Rain_Last_24_Hrs": True, "District": True}
    )
    fig.update_layout(margin={"r":0,"t":0,"l":0,"b":0})
    return fig

# ---------------------------- STREAMLIT UI ----------------------------
st.title("Gujarat Rainfall Dashboard")

rainfall_type = st.selectbox("Select Rainfall Type", ["2 Hourly", "24 Hourly"])

if rainfall_type == "24 Hourly":
    selected_date = st.date_input("Select Date", datetime.today())
    title = generate_title_from_date(selected_date)
    st.subheader(title)

    # Load rainfall data (sheet & tab assumed pre-created)
    sheet_name = f"24HR_Rainfall_{selected_date.strftime('%B_%Y')}"
    worksheet_name = selected_date.strftime("%d-%m-%Y")
    try:
        df = load_worksheet_df(sheet_name, worksheet_name)
        df["Rain_Last_24_Hrs"] = pd.to_numeric(df["Rain_Last_24_Hrs"], errors='coerce')

        # ---- Tiles ----
        state_avg = df["Rain_Last_24_Hrs"].mean()
        highest_taluka = df.loc[df["Rain_Last_24_Hrs"].idxmax()]
        percent_avg = df["Percent_Against_Avg"].mean()

        col1, col2, col3 = st.columns(3)
        col1.metric("Total Rainfall (State Avg.)", f"{state_avg:.1f} mm")
        col2.metric("Highest Rainfall Taluka", f"{highest_taluka['Taluka']} ({highest_taluka['Rain_Last_24_Hrs']} mm)")
        col3.metric("State Avg Percent Till Today", f"{percent_avg:.1f}%")

        # ---- Choropleth Map ----
        fig = plot_choropleth(df, "gujarat_taluka_clean.geojson")
        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Unable to load data: {e}")
