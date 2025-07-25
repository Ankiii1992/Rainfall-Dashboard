import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go # Added for potential empty figure
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import datetime, timedelta
import os # Make sure os is imported globally for the script

# ---------------------------- CONFIG ----------------------------
@st.cache_resource
def get_gsheet_client():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    return gspread.authorize(creds)

@st.cache_resource
def load_geojson(path):
    # import os # Moved to global import
    import json
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            geojson_data = json.load(f)
        return geojson_data
    st.error(f"GeoJSON file not found at: {path}")
    return None

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

def load_sheet_data(folder_name, year, month, sheet_name, tab_name):
    try:
        client = get_gsheet_client()
        sheet = client.open(sheet_name).worksheet(tab_name)
        df = pd.DataFrame(sheet.get_all_records())
        # Clean column names immediately after loading
        df.columns = df.columns.str.strip()
        # Rename columns to standard names if they exist and are different (from old code for consistency)
        df.rename(columns={"DISTRICT": "District", "TALUKA": "Taluka", "TOTAL": "Total_mm"}, inplace=True)
        return df
    except Exception as e:
        st.error(f"❌ Failed to load sheet '{sheet_name}' or tab '{tab_name}'. Please ensure the sheet/tab name is correct and the service account has access. Error: {e}")
        return pd.DataFrame()

# --- MODIFIED plot_choropleth function ---
def plot_choropleth(df, geojson_path, highlight_taluka=None):
    geojson_data = load_geojson(geojson_path)
    if not geojson_data:
        # st.error("❌ GeoJSON file not loaded. Cannot plot map.") # Already handled in load_geojson
        return go.Figure() # Return an empty figure

    df_plot = df.copy()
    df_plot["Taluka"] = df_plot["Taluka"].astype(str).str.strip().str.lower()
    df_plot["Rainfall_Category"] = df_plot["Rain_Last_24_Hrs"].apply(classify_rainfall)

    # Normalize GeoJSON properties for matching
    for feature in geojson_data["features"]:
        if "SUB_DISTRICT" in feature["properties"]:
            feature["properties"]["SUB_DISTRICT"] = feature["properties"]["SUB_DISTRICT"].strip().lower()

    # Create an outline for the highlighted Taluka if provided
    shapes = []
    if highlight_taluka:
        normalized_highlight_taluka = highlight_taluka.strip().lower()
        for feature in geojson_data["features"]:
            if feature["properties"].get("SUB_DISTRICT") == normalized_highlight_taluka:
                # Assuming simple polygon/multipolygon geometries
                if feature["geometry"]["type"] == "Polygon":
                    shapes.append({
                        'type': 'line',
                        'xref': 'x', 'yref': 'y',
                        'layer': 'above',
                        'line': {'color': 'red', 'width': 3},
                        'path': f'M {feature["geometry"]["coordinates"][0][0][0]} {feature["geometry"]["coordinates"][0][0][1]} ' +
                                'L ' + ' '.join([f'{x} {y}' for x, y in feature["geometry"]["coordinates"][0][1:]]) + ' Z'
                    })
                elif feature["geometry"]["type"] == "MultiPolygon":
                    for poly in feature["geometry"]["coordinates"]:
                        shapes.append({
                            'type': 'line',
                            'xref': 'x', 'yref': 'y',
                            'layer': 'above',
                            'line': {'color': 'red', 'width': 3},
                            'path': f'M {poly[0][0][0]} {poly[0][0][1]} ' +
                                    'L ' + ' '.join([f'{x} {y}' for x, y in poly[0][1:]]) + ' Z'
                        })


    fig = px.choropleth_mapbox(
        df_plot,
        geojson=geojson_data,
        featureidkey="properties.SUB_DISTRICT",
        locations="Taluka",
        color="Rainfall_Category",
        color_discrete_map=color_map,
        mapbox_style="open-street-map",
        zoom=6,
        center={"lat": 22.5, "lon": 71.5},
        opacity=0.75,
        hover_name="Taluka",
        hover_data={"Rain_Last_24_Hrs": ":.1f mm", "District": True}, # Added formatting for mm
        height=650,
        title="Gujarat Rainfall Distribution by Taluka" if not highlight_taluka else f"Rainfall Distribution - Highlight: {highlight_taluka}"
    )
    fig.update_layout(
        margin={"r":0,"t":0,"l":0,"b":0},
        uirevision='true', # Keep map state on rerun
        shapes=shapes # Add the highlight shapes
    )
    return fig


def show_24_hourly_dashboard(df, selected_date, selected_location=None):
    df["Rain_Last_24_Hrs"] = pd.to_numeric(df["Rain_Last_24_Hrs"], errors='coerce')
    
    # Filter data if a location is selected
    filtered_df = df.copy()
    if selected_location:
        # Check if selected_location is a Taluka or District
        # Assuming Taluka names are unique enough for this simple search.
        # For more robust search, might need a separate lookup or explicit selection type.
        is_taluka = selected_location.strip().lower() in df["Taluka"].astype(str).str.strip().str.lower().unique()
        if is_taluka:
            filtered_df = filtered_df[filtered_df["Taluka"].astype(str).str.strip().str.lower() == selected_location.strip().lower()]
        else: # Assume it's a District
            filtered_df = filtered_df[filtered_df["District"].astype(str).str.strip().str.lower() == selected_location.strip().lower()]

        if filtered_df.empty:
            st.warning(f"No data for '{selected_location}' found on this date.")
            return # Exit if no data after filtering

    title = generate_title_from_date(selected_date)
    st.subheader(title)

    # ---- Tiles ----
    # Handle empty filtered_df for metrics if no data for selected location
    state_avg = filtered_df["Rain_Last_24_Hrs"].mean() if not filtered_df.empty else 0.0
    highest_taluka = filtered_df.loc[filtered_df["Rain_Last_24_Hrs"].idxmax()] if not filtered_df.empty and not filtered_df["Rain_Last_24_Hrs"].isnull().all() else pd.Series({'Taluka': 'N/A', 'Rain_Last_24_Hrs': 0})
    percent_against_avg = filtered_df["Percent_Against_Avg"].mean() if "Percent_Against_Avg" in filtered_df.columns and not filtered_df.empty else 0.0

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-tile'><h4>Total Rainfall (Avg)</h4><h2>{state_avg:.1f} mm</h2></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with col2:
        st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-tile'><h4>Highest Rainfall Taluka</h4><h2>{highest_taluka['Taluka']}</h2><p>({highest_taluka['Rain_Last_24_Hrs']} mm)</p></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with col3:
        st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-tile'><h4>State Avg Percent Till Today</h4><h2>{percent_against_avg:.1f}%</h2></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # ---- Choropleth Map ----
    map_highlight_taluka = highest_taluka['Taluka'] if selected_location is None and not highest_taluka.empty else selected_location # Highlight selected if any, else highest
    
    # If a specific location is selected, center the map on it more closely if possible
    # This requires looking up lat/lon of the selected Taluka/District.
    # For now, we'll keep the general Gujarat view, but add a simple highlight.
    
    fig = plot_choropleth(df, "gujarat_taluka_clean.geojson", highlight_taluka=selected_location)
    st.plotly_chart(fig, use_container_width=True)

    # Display filtered data or full data as a table
    st.subheader("📋 Rainfall Data Table")
    display_df = filtered_df if selected_location else df
    df_display = display_df.sort_values(by="Rain_Last_24_Hrs", ascending=False).reset_index(drop=True)
    df_display.index += 1
    st.dataframe(df_display, use_container_width=True, height=400) # Reduced height slightly

# ---------------------------- UI ----------------------------
st.set_page_config(layout="wide")
st.title("Gujarat Rainfall Dashboard")

# --- Date Selection in Sidebar ---
st.sidebar.header("Date Selection")
selected_date = st.sidebar.date_input("Select Date", datetime.today(), help="Choose a specific date to view its rainfall summary.")

# Quick date navigation buttons (can be added here or in a dedicated section)
col_prev, col_today, col_next = st.sidebar.columns(3)
if col_prev.button("⬅️ Previous Day"):
    selected_date = selected_date - timedelta(days=1)
    st.session_state.selected_date = selected_date # Update session state to persist
    st.rerun() # Rerun app to apply date change
if col_today.button("🗓️ Today"):
    selected_date = datetime.today().date() # Ensure it's just date
    st.session_state.selected_date = selected_date
    st.rerun()
if col_next.button("Next Day ➡️", disabled=(selected_date >= datetime.today().date())):
    selected_date = selected_date + timedelta(days=1)
    st.session_state.selected_date = selected_date
    st.rerun()

# --- Maintain selected_date across reruns ---
if 'selected_date' not in st.session_state:
    st.session_state.selected_date = datetime.today().date()
# This ensures that if user clicks a button, the date_input reflects it
# And if they manually pick, it updates the session state
selected_date = st.session_state.selected_date

selected_year = selected_date.strftime("%Y")
selected_month = selected_date.strftime("%B")
selected_date_str = selected_date.strftime("%Y-%m-%d") # YYYY-MM-DD for GSheets tab names

# --- Main Content Tabs ---
tab_daily, tab_hourly, tab_historical = st.tabs(["Daily Summary", "Hourly Trends", "Historical Data (Coming Soon)"])

with tab_daily:
    st.header("Daily Rainfall Summary")

    # Load 24-hourly data
    folder_name_24hr = "Rainfall Dashboard/24 Hourly Sheets"
    sheet_name_24hr = f"24HR_Rainfall_{selected_month}_{selected_year}"
    tab_name_24hr = f"master24hrs_{selected_date_str}"

    df_24hr = load_sheet_data(folder_name_24hr, selected_year, selected_month, sheet_name_24hr, tab_name_24hr)

    if not df_24hr.empty:
        # Get unique Talukas and Districts for the search bar from the *loaded* data
        all_locations = sorted(list(df_24hr["Taluka"].astype(str).unique()) + list(df_24hr["District"].astype(str).unique()))
        
        selected_location = st.selectbox(
            "🔍 Search Taluka or District",
            [""] + all_locations, # Add empty string for no selection
            index=0,
            help="Select a specific Taluka or District to filter and highlight its rainfall data."
        )

        show_24_hourly_dashboard(df_24hr, selected_date, selected_location if selected_location else None)
    else:
        st.warning(f"⚠️ No 24-hourly data available for {selected_date_str}. Please select another date or check the data source.")

with tab_hourly:
    st.header("Hourly Rainfall Trends (2-Hourly)")
    folder_name_2hr = "Rainfall Dashboard/2 Hourly Sheets"
    sheet_name_2hr = f"2HR_Rainfall_{selected_month}_{selected_year}"
    tab_name_2hr = f"master2hrs_{selected_date_str}"

    df_2hr = load_sheet_data(folder_name_2hr, selected_year, selected_month, sheet_name_2hr, tab_name_2hr)

    if not df_2hr.empty:
        st.subheader("Raw 2 Hourly Data")
        st.dataframe(df_2hr, use_container_width=True)
        st.info("💡 **Next Steps:** We can add interactive charts (e.g., time series) for this data here once the daily summary is solid!")
    else:
        st.warning(f"⚠️ No 2-hourly data available for {selected_date_str}. Please select another date or check the data source.")

with tab_historical:
    st.header("Historical Rainfall Data")
    st.info("💡 **Coming Soon:** This section will feature aggregated monthly/seasonal data, year-on-year comparisons, and long-term trends.")
    st.write("We can discuss the strategy for loading and aggregating historical data once the daily view is finalized.")
