import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import datetime, timedelta
import os
import io
import re

# ---------------------------- CONFIG ----------------------------
@st.cache_resource
def get_gsheet_client():
    """
    Establishes a connection to Google Sheets using service account credentials.
    The credentials should be stored in Streamlit secrets.
    """
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    try:
        creds_dict = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Error connecting to Google Sheets: {e}")
        st.info("Please ensure your Google service account credentials are set up correctly in Streamlit's secrets.")
        return None

@st.cache_resource
def load_geojson(path):
    """Loads GeoJSON data from a local file path."""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            geojson_data = json.load(f)
        return geojson_data
    st.error(f"GeoJSON file not found at: {path}")
    return None

# --- Custom CSS for Styling ---
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
        box_shadow: 0 10px 28px rgba(0, 0, 0, 0.1);
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

    /* These CSS rules for the download button will likely NOT WORK if unsafe_allow_html=True */
    /* does not permit direct injection of elements to hide Streamlit's native components */
    .stDataFrame header {
        display: none !important;
    }
    [data-testid="stDataFrameToolbar"] button {
        display: none !important;
    }
    [data-testid="stDataFrameToolbar"] {
        display: none !important;
    }
</style>

<script>
    document.addEventListener('contextmenu', event => event.preventDefault());
</script>
""", unsafe_allow_html=True)


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

category_ranges = { # From reference code
    "No Rain": "0 mm",
    "Very Light": "0.1 – 2.4 mm",
    "Light": "2.5 – 7.5 mm",
    "Moderate": "7.6 – 35.5 mm",
    "Rather Heavy": "35.6 – 64.4 mm",
    "Heavy": "64.5 – 124.4 mm",
    "Very Heavy": "124.5 – 244.4 mm",
    "Extremely Heavy": "244.5 – 350 mm",
    "Exceptional": "> 350 mm"
}

def classify_rainfall(rainfall):
    if pd.isna(rainfall) or rainfall == 0:
        return "No Rain"
    elif rainfall > 0 and rainfall <= 2.4:
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

# Ensure the order of categories for the Plotly color scale and legend
ordered_categories = [
    "No Rain", "Very Light", "Light", "Moderate", "Rather Heavy",
    "Heavy", "Very Heavy", "Extremely Heavy", "Exceptional"
]


# ---------------------------- UTILITY FUNCTIONS ----------------------------

def generate_title_from_date(selected_date):
    start_date = (selected_date - timedelta(days=1)).strftime("%d-%m-%Y")
    end_date = selected_date.strftime("%d-%m-%Y")
    return f"24 Hours Rainfall Summary ({start_date} 06:00 AM to {end_date} 06:00 AM)"

def load_sheet_data(sheet_name, tab_name):
    try:
        client = get_gsheet_client()
        sheet = client.open(sheet_name).worksheet(tab_name)
        df = pd.DataFrame(sheet.get_all_records())
        df.columns = df.columns.str.strip()
        # Ensure column names are consistent early - only rename if 'TOTAL' is present
        if 'TOTAL' in df.columns:
            df.rename(columns={"DISTRICT": "District", "TALUKA": "Taluka", "TOTAL": "Total_mm"}, inplace=True)
        else: # For 2-hourly data where 'TOTAL' might not be a direct column
            df.rename(columns={"DISTRICT": "District", "TALUKA": "Taluka"}, inplace=True)
        return df
    except Exception as e:
        # st.error(f"Error loading data from sheet '{sheet_name}', tab '{tab_name}': {e}") # For debugging
        return pd.DataFrame() # Return empty DataFrame on failure

# --- START: USER-PROVIDED ZONAL SUMMARY LOGIC ---
def get_zonal_data(df):
    """
    Generates a zonal summary from a DataFrame that contains all required columns.
    It dynamically gets zone names from the data itself.
    """
    df_copy = df.copy()
    
    # Standardize column names by stripping spaces and converting to lowercase for robust matching
    df_copy.columns = [col.strip().lower() for col in df_copy.columns]
    
    # --- ADD THIS NEW LINE TO FIX ZONE TYPOS ---
    if 'zone' in df_copy.columns:
        df_copy['zone'] = df_copy['zone'].str.strip().str.upper().str.replace('GUJARA T', 'GUJARAT')

    # --- NEW LOGIC FOR FLEXIBLE COLUMN MATCHING ---
    # Define a mapping from the standardized required name to the column found in the DF
    col_mapping = {
        'zone': None,
        'avg_rain': None,
        'rain_till_yesterday': None,
        'rain_last_24_hrs': None,
        'total_rainfall': None,
        'percent_against_avg': None,
    }
    
    # Iterate through DF columns and find the best match for each required column
    standardized_cols = df_copy.columns
    for req_col, _ in col_mapping.items():
        if req_col == 'zone':
            # Handle the 'zone' column separately
            if 'zone' in standardized_cols:
                col_mapping['zone'] = 'zone'
            elif 'zonedistricttaluka' in standardized_cols:
                # This handles the case if the column is a single, combined one
                # but we need to split it first. Assuming we only get the simple case now.
                st.error("Please ensure 'Zone' is a separate column. The script cannot parse combined 'ZoneDistrictTaluka' header.")
                return pd.DataFrame()
        elif 'rain_till' in standardized_cols:
            col_mapping['rain_till_yesterday'] = 'rain_till'
        elif 'rain_last' in standardized_cols:
            col_mapping['rain_last_24_hrs'] = 'rain_last'
        elif 'total_rain' in standardized_cols:
            col_mapping['total_rainfall'] = 'total_rain'
        elif 'percent_a' in standardized_cols:
            col_mapping['percent_against_avg'] = 'percent_a'
        # General case
        elif req_col in standardized_cols:
            col_mapping[req_col] = req_col
    
    # Check if all required columns were found
    for req_col, found_col in col_mapping.items():
        if found_col is None:
            st.error(f"Required column for '{req_col}' not found in the data source. Please check your sheet headers.")
            return pd.DataFrame()

    # Rename the columns to the standard format for the rest of the function
    df_copy = df_copy.rename(columns={found: req for req, found in col_mapping.items()})
    
    # Check if the renamed columns exist before proceeding
    required_cols_standardized = list(col_mapping.keys())
    if not all(col in df_copy.columns for col in required_cols_standardized):
        st.error("Error standardizing columns. Some required columns are missing.")
        return pd.DataFrame()

    # Clean the data and convert to numeric, handling potential errors
    for col in required_cols_standardized[1:]:
        df_copy[col] = df_copy[col].astype(str).str.replace(' mm', '').str.replace('%', '')
        df_copy[col] = pd.to_numeric(df_copy[col], errors='coerce')

    # Get the unique zones directly from the data and sort them
    unique_zones = sorted(df_copy['zone'].unique())

    # Group by the dynamically found zone column and calculate averages
    zonal_averages = df_copy.groupby('zone')[['avg_rain', 'rain_till_yesterday', 'rain_last_24_hrs', 'total_rainfall', 'percent_against_avg']].mean().round(2)
    
    # Reorder the DataFrame using the unique zones from the data
    final_results = zonal_averages.reindex(unique_zones).reset_index()
    
    # Revert column names to the original format for display
    final_results = final_results.rename(columns={
        'zone': 'Zone',
        'avg_rain': 'Avg_Rain',
        'rain_till_yesterday': 'Rain_Till_Yesterday',
        'rain_last_24_hrs': 'Rain_Last_24_Hrs',
        'total_rainfall': 'Total_Rainfall',
        'percent_against_avg': 'Percent_Against_Avg'
    })

    return final_results


def generate_zonal_summary_table(df_zonal_averages, df_full_data):
    """Generates a formatted table with zonal averages and a state-wide average row."""
    if df_zonal_averages.empty or df_full_data.empty:
        return pd.DataFrame()

    df_zonal_averages_copy = df_zonal_averages.copy()
    
    # Calculate state-wide averages from the full dataset
    state_avg = df_full_data[['Avg_Rain', 'Rain_Till_Yesterday', 'Rain_Last_24_Hrs', 'Total_Rainfall', 'Percent_Against_Avg']].mean().round(2)
    
    # Create a new DataFrame for the state average row
    state_avg_row = pd.DataFrame([state_avg.to_dict()])
    state_avg_row['Zone'] = 'State Avg.'
    
    # Concatenate the zonal averages with the state average row
    final_table = pd.concat([df_zonal_averages_copy, state_avg_row], ignore_index=True)
    
    # Format the columns for display
    for col in ['Avg_Rain', 'Rain_Till_Yesterday', 'Rain_Last_24_Hrs', 'Total_Rainfall']:
        final_table[col] = final_table[col].astype(str) + ' mm'
    final_table['Percent_Against_Avg'] = final_table['Percent_Against_Avg'].astype(str) + '%'
    
    # Rename columns for better display
    final_table = final_table.rename(columns={
        'Avg_Rain': 'Avg_Rain (mm)',
        'Rain_Till_Yesterday': 'Rain_Till_Yesterday (mm)',
        'Rain_Last_24_Hrs': 'Rain_Last_24_Hrs (mm)',
        'Total_Rainfall': 'Total_Rainfall (mm)',
        'Percent_Against_Avg': 'Percent_Against_Avg'
    })
    
    return final_table
# --- END: USER-PROVIDED ZONAL SUMMARY LOGIC ---


def create_zonal_dual_axis_chart(data):
    """Creates a dual-axis chart for zonal rainfall."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    # The dataframe passed to this function must have standardized column names.
    # The user's get_zonal_data renames columns for display, so we have to use
    # standardized names for the chart
    data = data.rename(columns={
        'Zone': 'zone',
        'Avg_Rain': 'avg_rain',
        'Rain_Till_Yesterday': 'rain_till_yesterday',
        'Rain_Last_24_Hrs': 'rain_last_24_hrs',
        'Total_Rainfall': 'total_rainfall',
        'Percent_Against_Avg': 'percent_against_avg'
    })
    
    fig.add_trace(
        go.Bar(
            x=data['zone'],
            y=data['total_rainfall'],
            name='Total Rainfall (mm)',
            marker_color='rgb(100, 149, 237)',
            text=data['total_rainfall'],
            textposition='inside',
        ),
        secondary_y=False,
    )
    
    fig.add_trace(
        go.Scatter(
            x=data['zone'],
            y=data['percent_against_avg'],
            name='% Against Avg. Rainfall',
            mode='lines+markers+text',
            marker=dict(size=8, color='rgb(255, 165, 0)'),
            line=dict(color='rgb(255, 165, 0)'),
            text=[f'{p:.1f}%' for p in data['percent_against_avg']],
            textposition='top center',
        ),
        secondary_y=True,
    )
    
    fig.update_layout(
        title_text='Zonewise Total Rainfall vs. % Against Average',
        height=450,
        margin=dict(l=0, r=0, t=50, b=0),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.3,
            xanchor="center",
            x=0.5
        )
    )
    
    fig.update_yaxes(title_text="Total Rainfall (mm)", secondary_y=False)
    fig.update_yaxes(title_text="% Against Avg. Rainfall", secondary_y=True)
    
    return fig


# --- plot_choropleth function (for map that plots daily total) ---
def plot_choropleth(df, geojson_path, title="Gujarat Rainfall Distribution", geo_feature_id_key="properties.SUB_DISTRICT", geo_location_col="Taluka"):
    # This function is now made more generic to handle both talukas and districts
    geojson_data = load_geojson(geojson_path)
    if not geojson_data:
        return go.Figure()

    df_plot = df.copy()

    # Determine which column to use for feature linking and what to strip/lower
    if geo_location_col == "Taluka":
        df_plot["Taluka"] = df_plot["Taluka"].astype(str).str.strip().str.lower()
    elif geo_location_col == "District":
        df_plot["District"] = df_plot["District"].astype(str).str.strip().str.lower()


    # The column for coloring the map should be 'Total_mm' (daily total for taluka)
    # or 'District_Avg_Rain_Last_24_Hrs' for district.
    color_column = None
    if 'Total_mm' in df_plot.columns: # For Talukas
        color_column = 'Total_mm'
    elif 'District_Avg_Rain_Last_24_Hrs' in df_plot.columns: # For Districts
        color_column = 'District_Avg_Rain_Last_24_Hrs'
    else:
        st.warning(f"Neither 'Total_mm' nor 'District_Avg_Rain_Last_24_Hrs' found for map categorization. Map may not display categories correctly.")
        df_plot["Rainfall_Category"] = "No Rain" # Default if data is missing
        color_column = "Rainfall_Category"


    if color_column:
        df_plot[color_column] = pd.to_numeric(df_plot[color_column], errors='coerce')
        df_plot["Rainfall_Category"] = df_plot[color_column].apply(classify_rainfall)
        df_plot["Rainfall_Category"] = pd.Categorical(
            df_plot["Rainfall_Category"],
            categories=ordered_categories,
            ordered=True
        )

    # Clean geojson properties for matching
    for feature in geojson_data["features"]:
        if geo_feature_id_key == "properties.SUB_DISTRICT" and "SUB_DISTRICT" in feature["properties"]:
            feature["properties"]["SUB_DISTRICT"] = feature["properties"]["SUB_DISTRICT"].strip().lower()
        elif geo_feature_id_key == "properties.district" and "district" in feature["properties"]:
            feature["properties"]["district"] = feature["properties"]["district"].strip().lower()


    fig = px.choropleth_mapbox(
        df_plot,
        geojson=geojson_data,
        featureidkey=geo_feature_id_key, # Dynamic key for Taluka or District
        locations=geo_location_col,     # Dynamic column for Taluka or District
        color="Rainfall_Category",
        color_discrete_map=color_map,
        mapbox_style="open-street-map",
        zoom=6,
        center={"lat": 22.5, "lon": 71.5},
        opacity=0.75,
        hover_name=geo_location_col, # Use dynamic column for hover name
        hover_data={
            color_column: ":.1f mm", # Show actual rainfall value
            "District": True if geo_location_col == "Taluka" else False, # Only show district for taluka map
            "Rainfall_Category":False
        },
        height=650,
        title=title
    )
    fig.update_layout(
        margin={"r":0,"t":0,"l":0,"b":0},
        uirevision='true',
        showlegend=True, # Ensure legend is shown for map
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.15,
            xanchor="center",
            x=0.5,
            title_text="Rainfall Categories (mm)",
            font=dict(size=10),
            itemsizing='constant',
        )
    )
    return fig


# --- show_24_hourly_dashboard function (for Daily Summary tab - NOW INCLUDES ALL DAILY CHARTS) ---
def show_24_hourly_dashboard(df, selected_date):
    # Rename 'Rain_Last_24_Hrs' to 'Total_mm' for consistency if it's the 24hr data source
    if "Rain_Last_24_Hrs" in df.columns:
        df.rename(columns={"Rain_Last_24_Hrs": "Total_mm"}, inplace=True)

    required_cols = ["Total_mm", "Taluka", "District"]
    for col in required_cols:
        if col not in df.columns:
            st.error(f"Required column '{col}' not found in the loaded data. Please check your Google Sheet headers for 24-hour data.")
            return

    df["Total_mm"] = pd.to_numeric(df["Total_mm"], errors='coerce')

    # --- NEW CODE START: District Name Standardization ---
    # Define mapping for known district name discrepancies
    district_name_mapping = {
        "Chhota Udepur": "Chhota Udaipur",
        "Dangs": "Dang",
        "Kachchh": "Kutch",
        "Mahesana": "Mehsana",
        # Add more mappings here if you discover other mismatches
    }

    # Apply the mapping to the 'District' column
    df['District'] = df['District'].replace(district_name_mapping)

    # Ensure consistent casing and stripping for matching with GeoJSON
    # This also handles cases where a district name might just have leading/trailing spaces
    df['District'] = df['District'].astype(str).str.strip()
    # --- NEW CODE END: District Name Standardization ---

    title = generate_title_from_date(selected_date)
    st.subheader(title)

    # ---- Metrics ----
    state_avg = df["Total_mm"].mean() if not df["Total_mm"].isnull().all() else 0.0

    if not df["Total_mm"].isnull().all() and not df.empty:
        highest_taluka = df.loc[df["Total_mm"].idxmax()]
    else:
        highest_taluka = pd.Series({'Taluka': 'N/A', 'Total_mm': 0})

    # The user's code expects columns like `Percent_Against_Avg` to be present
    percent_against_avg = df["Percent_Against_Avg"].mean() if "Percent_Against_Avg" in df.columns and not df["Percent_Against_Avg"].isnull().all() else 0.0

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-tile'><h4>State Rainfall (Avg.)</h4><h2>{state_avg:.1f} mm</h2></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with col2:
        st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-tile'><h4>Highest Rainfall Taluka</h4><h2>{highest_taluka['Taluka']}</h2><p>({highest_taluka['Total_mm']} mm)</p></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with col3:
        st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-tile'><h4>State Avg Rainfall (%) Till Today</h4><h2>{percent_against_avg:.1f}%</h2></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")
    col_daily_1, col_daily_2, col_daily_3 = st.columns(3)

    more_than_200_daily = df[df['Total_mm'] > 200].shape[0]
    more_than_100_daily = df[df['Total_mm'] > 100].shape[0]
    more_than_50_daily = df[df['Total_mm'] > 50].shape[0]

    with col_daily_1:
        st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-tile'><h4>Talukas > 200 mm</h4><h2>{more_than_200_daily}</h2></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with col_daily_2:
        st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-tile'><h4>Talukas > 100 mm</h4><h2>{more_than_100_daily}</h2></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with col_daily_3:
        st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-tile'><h4>Talukas > 50 mm</h4><h2>{more_than_50_daily}</h2></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")

  # --- MODIFIED: ZONAL SUMMARY SECTION ---
    st.header("Zonewise Rainfall (Average) Summary Table")

    zonal_summary_averages = get_zonal_data(df_daily_copy)

    if not zonal_summary_averages.empty:
        col_table, col_chart = st.columns([1, 1])
        
        df_daily_renamed_for_table = df_daily_copy.rename(columns={
            'avg_rain': 'Avg_Rain', 'rain_till_yesterday': 'Rain_Till_Yesterday',
            'rain_last_24_hrs': 'Rain_Last_24_Hrs', 'total_rainfall': 'Total_Rainfall',
            'percent_against_avg': 'Percent_Against_Avg'
        })
        
        zonal_summary_table_df = generate_zonal_summary_table(zonal_summary_averages, df_daily_renamed_for_table)

        with col_table:
            st.markdown("#### Rainfall Averages by Zone")
            
            if not zonal_summary_table_df.empty:
                st.dataframe(zonal_summary_table_df.style.set_properties(**{'font-weight': 'bold'}, subset=pd.IndexSlice[-1:, :]), use_container_width=True)
            else:
                st.warning("Could not generate Zonewise Summary. Please ensure your data source contains the required columns and is loaded correctly.")

        with col_chart:
            st.markdown("#### Zonewise Rainfall vs. % Against Avg.")
            fig = create_zonal_dual_axis_chart(zonal_summary_averages)
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("Could not generate Zonewise Summary. Please ensure your data source contains the required columns and is loaded correctly.")
    # --- MODIFIED: END ZONAL SUMMARY SECTION ---

    st.markdown("---")
    st.markdown("### 🗺️ Rainfall Distribution Overview")

    district_rainfall_avg_df = df.groupby('District')['Total_mm'].mean().reset_index()
    district_rainfall_avg_df = district_rainfall_avg_df.rename(
        columns={'Total_mm': 'District_Avg_Rain_Last_24_Hrs'}
    )
    district_rainfall_avg_df["Rainfall_Category"] = district_rainfall_avg_df["District_Avg_Rain_Last_24_Hrs"].apply(classify_rainfall)
    district_rainfall_avg_df["Rainfall_Category"] = pd.Categorical(
        district_rainfall_avg_df["Rainfall_Category"],
        categories=ordered_categories,
        ordered=True
    )
    district_rainfall_avg_df['Rainfall_Range'] = district_rainfall_avg_df['Rainfall_Category'].map(category_ranges)


    df_map_talukas = df.copy()
    df_map_talukas["Taluka"] = df_map_talukas["Taluka"].str.strip().str.lower()
    df_map_talukas["Rainfall_Category"] = df_map_talukas["Total_mm"].apply(classify_rainfall)
    df_map_talukas["Rainfall_Category"] = pd.Categorical(
        df_map_talukas["Rainfall_Category"],
        categories=ordered_categories,
        ordered=True
    )
    df_map_talukas["Rainfall_Range"] = df_map_talukas["Rainfall_Category"].map(category_ranges)

    taluka_geojson = load_geojson("gujarat_taluka_clean.geojson")
    district_geojson = load_geojson("gujarat_district_clean.geojson")


    if not taluka_geojson or not district_geojson:
        st.error("Cannot display maps: One or both GeoJSON files not found or loaded correctly.")
        return

    tab_districts, tab_talukas = st.tabs(["Rainfall Distribution by Districts", "Rainfall Distribution by Talukas"])


    with tab_districts:
        map_col_dist, insights_col_dist = st.columns([0.5, 0.5])

        with map_col_dist:
            st.markdown("#### Gujarat Rainfall Map (by District)")
            with st.spinner("Loading district map..."):
                fig_map_districts = plot_choropleth(
                    district_rainfall_avg_df,
                    "gujarat_district_clean.geojson",
                    title="Gujarat Daily Rainfall Distribution by District",
                    geo_feature_id_key="properties.district",
                    geo_location_col="District"
                )
                st.plotly_chart(fig_map_districts, use_container_width=True)

        with insights_col_dist:
            st.markdown("#### Key Insights & Distributions (Districts)")

            category_counts_dist = district_rainfall_avg_df['Rainfall_Category'].value_counts().reset_index()
            category_counts_dist.columns = ['Category', 'Count']
            category_counts_dist['Category'] = pd.Categorical(
                category_counts_dist['Category'],
                categories=ordered_categories,
                ordered=True
            )
            category_counts_dist = category_counts_dist.sort_values('Category')
            category_counts_dist['Rainfall_Range'] = category_counts_dist['Category'].map(category_ranges)


            fig_category_dist_dist = px.bar(
                category_counts_dist,
                x='Category',
                y='Count',
                title='Distribution of Districts by Daily Rainfall Category',
                labels={'Count': 'Number of Districts'},
                color='Category',
                color_discrete_map=color_map,
                hover_data={
                    'Category': True,
                    'Rainfall_Range': True,
                    'Count': True
                }
            )
            fig_category_dist_dist.update_layout(
                xaxis=dict(
                    tickmode='array',
                    tickvals=category_counts_dist['Category'],
                    ticktext=[cat for cat in category_counts_dist['Category']],
                    tickangle=0
                ),
                xaxis_title=None,
                showlegend=False,
                height=350,
                margin=dict(l=0, r=0, t=50, b=0)
            )
            st.plotly_chart(fig_category_dist_dist, use_container_width=True)


    with tab_talukas:
        map_col_tal, insights_col_tal = st.columns([0.5, 0.5])

        with map_col_tal:
            st.markdown("#### Gujarat Rainfall Map (by Taluka)")
            with st.spinner("Loading taluka map..."):
                fig_map_talukas = plot_choropleth(
                    df_map_talukas,
                    "gujarat_taluka_clean.geojson",
                    title="Gujarat Daily Rainfall Distribution by Taluka",
                    geo_feature_id_key="properties.SUB_DISTRICT",
                    geo_location_col="Taluka"
                )
                st.plotly_chart(fig_map_talukas, use_container_width=True)

        with insights_col_tal:
            st.markdown("#### Key Insights & Distributions (Talukas)")

            TOTAL_TALUKAS_GUJARAT = 251
            num_talukas_with_rain_today = df_map_talukas[df_map_talukas['Total_mm'] > 0].shape[0]
            talukas_without_rain = TOTAL_TALUKAS_GUJARAT - num_talukas_with_rain_today

            pie_data = pd.DataFrame({
                'Category': ['Talukas with Rainfall', 'Talukas without Rainfall'],
                'Count': [num_talukas_with_rain_today, talukas_without_rain]
            })

            fig_pie = px.pie(
                pie_data,
                values='Count',
                names='Category',
                title="Percentage of Talukas with Daily Rainfall",
                color='Category',
                color_discrete_map={
                    'Talukas with Rainfall': '#28a745',
                    'Talukas without Rainfall': '#dc3545'
                }
            )
            fig_pie.update_traces(textinfo='percent+label', pull=[0.05 if cat == 'Talukas with Rainfall' else 0 for cat in pie_data['Category']])
            fig_pie.update_layout(showlegend=False, height=300, margin=dict(l=0, r=0, t=50, b=0))
            st.plotly_chart(fig_pie, use_container_width=True)

            category_counts_tal = df_map_talukas['Rainfall_Category'].value_counts().reset_index()
            category_counts_tal.columns = ['Category', 'Count']
            category_counts_tal['Category'] = pd.Categorical(
                category_counts_tal['Category'],
                categories=ordered_categories,
                ordered=True
            )
            category_counts_tal = category_counts_tal.sort_values('Category')
            category_counts_tal['Rainfall_Range'] = category_counts_tal['Category'].map(category_ranges)


            fig_category_dist_tal = px.bar(
                category_counts_tal,
                x='Category',
                y='Count',
                title='Distribution of Talukas by Daily Rainfall Category',
                labels={'Count': 'Number of Talukas'},
                color='Category',
                color_discrete_map=color_map,
                hover_data={
                    'Category': True,
                    'Rainfall_Range': True,
                    'Count': True
                }
            )
            fig_category_dist_tal.update_layout(
                xaxis=dict(
                    tickmode='array',
                    tickvals=category_counts_tal['Category'],
                    ticktext=[cat for cat in category_counts_tal['Category']],
                    tickangle=0
                ),
                xaxis_title=None,
                showlegend=False,
                height=350,
                margin=dict(l=0, r=0, t=50, b=0)
            )
            st.plotly_chart(fig_category_dist_tal, use_container_width=True)


    st.markdown("---")
    st.markdown("### 🏆 Top 10 Talukas by Total Rainfall")
    df_top_10 = df.dropna(subset=['Total_mm']).sort_values(by='Total_mm', ascending=False).head(10)

    if not df_top_10.empty:
        fig_top_10 = px.bar(
            df_top_10,
            x='Taluka',
            y='Total_mm',
            color='Total_mm',
            color_continuous_scale=px.colors.sequential.Bluyl,
            labels={'Total_mm': 'Total Rainfall (mm)'},
            hover_data=['District'],
            text='Total_mm',
            title='Top 10 Talukas with Highest Total Daily Rainfall'
        )
        fig_top_10.update_traces(texttemplate='%{text:.1f}', textposition='outside')
        fig_top_10.update_layout(
            xaxis_tickangle=-45,
            showlegend=False,
            margin=dict(t=50),
            coloraxis_showscale=False
        )
        st.plotly_chart(fig_top_10, use_container_width=True)
    else:
        st.info("No rainfall data available to determine top 10 talukas.")

    st.subheader("📋 Full Daily Rainfall Data Table")
    df_display = df.sort_values(by="Total_mm", ascending=False).reset_index(drop=True)
    df_display.index += 1
    st.dataframe(df_display, use_container_width=True, height=400)


# ---------------------------- UI ----------------------------
st.set_page_config(layout="wide")
st.markdown("<div class='title-text'>🌧️ Gujarat Rainfall Dashboard</div>", unsafe_allow_html=True)

st.markdown("---")
st.subheader("🗓️ Select Date for Rainfall Data")

if 'selected_date' not in st.session_state:
    st.session_state.selected_date = datetime.today().date()

col_date_picker, col_prev_btn, col_today_btn, col_next_btn = st.columns([0.2, 0.1, 0.1, 0.1])

with col_date_picker:
    selected_date_from_picker = st.date_input(
        "Choose Date",
        value=st.session_state.selected_date,
        help="Select a specific date to view its rainfall summary."
    )
    if selected_date_from_picker != st.session_state.selected_date:
        st.session_state.selected_date = selected_date_from_picker
        st.rerun()

selected_date = st.session_state.selected_date

with col_prev_btn:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("⬅️ Previous Day", key="prev_day_btn"):
        st.session_state.selected_date = selected_date - timedelta(days=1)
        st.rerun()

with col_today_btn:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🗓️ Today", key="today_btn"):
        st.session_state.selected_date = datetime.today().date()
        st.rerun()

with col_next_btn:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Next Day ➡️", key="next_day_btn", disabled=(selected_date >= datetime.today().date())):
        st.session_state.selected_date = selected_date + timedelta(days=1)
        st.rerun()

st.markdown("---")

selected_year = selected_date.strftime("%Y")
selected_month = selected_date.strftime("%B")
selected_date_str = selected_date.strftime("%Y-%m-%d")

tab_daily, tab_hourly, tab_historical = st.tabs(["Daily Summary", "Hourly Trends", "Historical Data (Coming Soon)"])

with tab_daily:
    st.header("Daily Rainfall Summary")

    sheet_name_24hr = f"24HR_Rainfall_{selected_month}_{selected_year}"
    tab_name_24hr = f"master24hrs_{selected_date_str}"

    df_24hr = load_sheet_data(sheet_name_24hr, tab_name_24hr)

    if not df_24hr.empty:
        show_24_hourly_dashboard(df_24hr, selected_date)
    else:
        st.warning(f"⚠️ Daily data is not available for {selected_date_str}.")

with tab_hourly:
    st.header("Hourly Rainfall Trends (2-Hourly)")
    sheet_name_2hr = f"2HR_Rainfall_{selected_month}_{selected_year}"
    tab_name_2hr = f"2hrs_master_{selected_date_str}"

    df_2hr = load_sheet_data(sheet_name_2hr, tab_name_2hr)

    if not df_2hr.empty:
        df_2hr.columns = df_2hr.columns.str.strip()

        time_slot_columns = [col for col in df_2hr.columns if "TO" in col and df_2hr[col].dtype in ['int64', 'float64', 'object']]
        time_slot_order = ['06TO08', '08TO10', '10TO12', '12TO14', '14TO16', '16TO18',
                           '18TO20', '20TO22', '22TO24', '24TO02', '02TO04', '04TO06']
        existing_order = [slot for slot in time_slot_order if slot in time_slot_columns]

        for col in existing_order:
            df_2hr[col] = pd.to_numeric(df_2hr[col], errors="coerce")

        df_2hr['Total_mm'] = df_2hr[existing_order].sum(axis=1)

        df_long = df_2hr.melt(
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

        slot_labels = {
            "06TO08": "6–8 AM", "08TO10": "8–10 AM", "10TO12": "10–12 AM",
            "12TO14": "12–2 PM", "14TO16": "2–4 PM", "16TO18": "4–6 PM",
            "18TO20": "6–8 PM", "20TO22": "8–10 PM", "22TO24": "10–12 PM",
            "24TO02": "12–2 AM", "02TO04": "2–4 AM", "04TO06": "4–6 AM",
        }
        df_long['Time Slot Label'] = pd.Categorical(
            df_long['Time Slot'].map(slot_labels),
            categories=[slot_labels[slot] for slot in existing_order],
            ordered=True
        )
        df_long = df_long.sort_values(by=["Taluka", "Time Slot Label"])


        df_2hr['Total_mm'] = pd.to_numeric(df_2hr['Total_mm'], errors='coerce')

        top_taluka_row = df_2hr.sort_values(by='Total_mm', ascending=False).iloc[0] if not df_2hr['Total_mm'].dropna().empty else pd.Series({'Taluka': 'N/A', 'Total_mm': 0})
        df_latest_slot = df_long[df_long['Time Slot'] == existing_order[-1]]
        top_latest = df_latest_slot.sort_values(by='Rainfall (mm)', ascending=False).iloc[0] if not df_latest_slot['Rainfall (mm)'].dropna().empty else pd.Series({'Taluka': 'N/A', 'Rainfall (mm)': 0})
        num_talukas_with_rain_hourly = df_2hr[df_2hr['Total_mm'] > 0].shape[0]

        st.markdown(f"#### 📊 Latest data available for time interval: **{slot_labels[existing_order[-1]]}**")

        row1 = st.columns(3)

        last_slot_label = slot_labels[existing_order[-1]]

        row1_titles = [
            ("Total Talukas with Rainfall", num_talukas_with_rain_hourly),
            ("Top Taluka by Total Rainfall", f"{top_taluka_row['Taluka']}<br><p>{top_taluka_row['Total_mm']:.1f} mm</p>"),
            (f"Top Taluka in last 2 hour ({last_slot_label})", f"{top_latest['Taluka']}<br><p>{top_latest['Rainfall (mm)']:.1f} mm</p>")
        ]

        for col, (label, value) in zip(row1, row1_titles):
            with col:
                st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
                st.markdown(f"<div class='metric-tile'><h4>{label}</h4><h2>{value}</h2></div>", unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("### 📈 Rainfall Trend by 2 hourly Time Interval")
        selected_talukas = st.multiselect("Select Taluka(s)", sorted(df_long['Taluka'].unique()), default=[top_taluka_row['Taluka']] if top_taluka_row['Taluka'] != 'N/A' else [])

        if selected_talukas:
            plot_df = df_long[df_long['Taluka'].isin(selected_talukas)]
            fig = px.line(
                plot_df,
                x="Time Slot Label",
                y="Rainfall (mm)",
                color="Taluka",
                markers=True,
                text="Rainfall (mm)",
                title="Rainfall Trend Over Time for Selected Talukas",
                labels={"Rainfall (mm)": "Rainfall (mm)"}
            )
            fig.update_traces(textposition="top center")
            fig.update_layout(showlegend=True)
            fig.update_layout(modebar_remove=['toImage'])
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Please select at least one Taluka to view the rainfall trend.")


        st.markdown("### 📋 Full 2-Hourly Rainfall Data Table")
        df_display_2hr = df_2hr.sort_values(by="Total_mm", ascending=False).reset_index(drop=True)
        df_display_2hr.index += 1
        st.dataframe(df_display_2hr, use_container_width=True, height=600)

    else:
        st.warning(f"⚠️ 2-Hourly data is not available for {selected_date_str}.")


with tab_historical:
    st.header("Historical Rainfall Data")
    st.info("💡 **Coming Soon:** This section will feature monthly/seasonal data, year-on-year comparisons, and long-term trends.")
