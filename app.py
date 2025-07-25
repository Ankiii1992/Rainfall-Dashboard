import streamlit as st
import pandas as pd
import plotly.express as px
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import datetime, timedelta
# import geopandas as gpd # We might not need this if we're directly passing the geojson dict

# ---------------------------- CONFIG ----------------------------
@st.cache_resource
def get_gsheet_client():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    return gspread.authorize(creds)

@st.cache_resource # Cache the GeoJSON loading
def load_geojson(path):
    import json # Import json here to keep load_geojson self-contained
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            geojson_data = json.load(f)
        return geojson_data
    return None

# --- Rainfall Category & Color Mapping (for Plotly map) ---
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

def load_sheet_data(folder_name, year, month, sheet_name, tab_name):
    try:
        client = get_gsheet_client()
        sheet = client.open(sheet_name).worksheet(tab_name)
        df = pd.DataFrame(sheet.get_all_records())
        return df
    except Exception as e:
        st.error(f"❌ Failed to load sheet '{sheet_name}' or tab '{tab_name}': {e}")
        return pd.DataFrame()

# --- MODIFIED plot_choropleth function ---
def plot_choropleth(df, geojson_path):
    geojson_data = load_geojson(geojson_path)
    if not geojson_data:
        st.error("❌ GeoJSON file not loaded. Cannot plot map.")
        return go.Figure() # Return an empty figure

    # Ensure Taluka names in DataFrame are consistent with GeoJSON property for matching
    # The old code used .strip().lower() on the 'Taluka' column of df_map
    df_plot = df.copy() # Work on a copy to avoid modifying original df
    df_plot["Taluka"] = df_plot["Taluka"].astype(str).str.strip().str.lower()
    df_plot["Rainfall_Category"] = df_plot["Rain_Last_24_Hrs"].apply(classify_rainfall)

    # Normalize GeoJSON properties for matching
    # The old code modified the GeoJSON in place: feature["properties"]["SUB_DISTRICT"] = feature["properties"]["SUB_DISTRICT"].strip().lower()
    # Let's ensure this is handled for the choropleth
    for feature in geojson_data["features"]:
        if "SUB_DISTRICT" in feature["properties"]:
            feature["properties"]["SUB_DISTRICT"] = feature["properties"]["SUB_DISTRICT"].strip().lower()

    fig = px.choropleth_mapbox(
        df_plot, # Use the prepared df_plot
        geojson=geojson_data, # Pass the raw GeoJSON dictionary
        featureidkey="properties.SUB_DISTRICT", # Match 'Taluka' from df to 'SUB_DISTRICT' in geojson properties
        locations="Taluka", # Column in df_plot
        color="Rainfall_Category",
        color_discrete_map=color_map,
        mapbox_style="open-street-map", # Used "open-street-map" in old code, "carto-positron" in new
        zoom=6, # Adjusted to match old code's zoom
        center={"lat": 22.5, "lon": 71.5}, # Adjusted to match old code's center
        opacity=0.75, # Adjusted to match old code's opacity
        hover_name="Taluka",
        hover_data={"Rain_Last_24_Hrs": True, "District": True},
        height=650 # Adjusted to match old code's height
    )
    fig.update_layout(margin={"r":0,"t":0,"l":0,"b":0})
    return fig

def show_24_hourly_dashboard(df, selected_date):
    df["Rain_Last_24_Hrs"] = pd.to_numeric(df["Rain_Last_24_Hrs"], errors='coerce')
    title = generate_title_from_date(selected_date)
    st.subheader(title)

    # ---- Tiles ----
    state_avg = df["Rain_Last_24_Hrs"].mean()
    highest_taluka = df.loc[df["Rain_Last_24_Hrs"].idxmax()]
    # Assuming "Percent_Against_Avg" is present in your new GSheet data
    # If not, remove or handle this line gracefully
    percent_against_avg = df["Percent_Against_Avg"].mean() if "Percent_Against_Avg" in df.columns else 0.0

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Rainfall (State Avg.)", f"{state_avg:.1f} mm")
    col2.metric("Highest Rainfall Taluka", f"{highest_taluka['Taluka']} ({highest_taluka['Rain_Last_24_Hrs']} mm)")
    col3.metric("State Avg Percent Till Today", f"{percent_against_avg:.1f}%") # Use percent_against_avg

    # ---- Choropleth Map ----
    fig = plot_choropleth(df, "gujarat_taluka_clean.geojson")
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------- UI ----------------------------
st.set_page_config(layout="wide")
st.title("Gujarat Rainfall Dashboard")

data_type = st.radio("Select Rainfall Data Type", ["2 Hourly Rainfall", "24 Hourly Rainfall"])
selected_date = st.date_input("Select Date", datetime.today())

selected_year = selected_date.strftime("%Y")
selected_month = selected_date.strftime("%B")
selected_date_str = selected_date.strftime("%Y-%m-%d") # Changed to YYYY-MM-DD as per your GeoSheet tab name

if data_type == "24 Hourly Rainfall":
    folder_name = "Rainfall Dashboard/24 Hourly Sheets" # This isn't actually used in load_sheet_data
    sheet_name = f"24HR_Rainfall_{selected_month}_{selected_year}"
    tab_name = f"master24hrs_{selected_date_str}"

    df = load_sheet_data(folder_name, selected_year, selected_month, sheet_name, tab_name)

    if not df.empty:
        # Ensure 'Rain_Last_24_Hrs' and 'Taluka' columns exist for 24-hour data
        if "Rain_Last_24_Hrs" not in df.columns:
            st.error("Column 'Rain_Last_24_Hrs' not found in the loaded data for 24 Hourly Rainfall.")
            df["Rain_Last_24_Hrs"] = 0 # Add a placeholder to prevent further errors
        if "Taluka" not in df.columns:
            st.error("Column 'Taluka' not found in the loaded data for 24 Hourly Rainfall.")
            df["Taluka"] = "" # Add a placeholder
        
        show_24_hourly_dashboard(df, selected_date)
    else:
        st.warning("⚠️ No data available for this date.")

elif data_type == "2 Hourly Rainfall":
    folder_name = "Rainfall Dashboard/2 Hourly Sheets" # This isn't actually used in load_sheet_data
    sheet_name = f"2HR_Rainfall_{selected_month}_{selected_year}"
    tab_name = f"master2hrs_{selected_date_str}" # This will also now be YYYY-MM-DD

    df = load_sheet_data(folder_name, selected_year, selected_month, sheet_name, tab_name)

    if not df.empty:
        st.subheader("📊 2 Hourly Rainfall Data")
        st.dataframe(df)
    else:
        st.warning("⚠️ No data available for this date.")
