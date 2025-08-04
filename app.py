import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import datetime, timedelta
import os
import io

# ---------------------------- CONFIG ----------------------------
@st.cache_resource
def get_gsheet_client():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    return gspread.authorize(creds)

@st.cache_resource
def load_geojson(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            geojson_data = json.load(f)
        return geojson_data
    st.error(f"GeoJSON file not found at: {path}")
    return None

# --- NEW: Enhanced CSS (from reference code) ---
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
        height: 165px; /* Adjusted height for consistency */
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
        locations=geo_location_col,     # Dynamic column for Taluka or District
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

# Date picker and navigation buttons remain the same
if 'selected_date' not in st.session_state:
    st.session_state.selected_date = datetime.today().date()
# ... (Code for date picker and navigation buttons) ...

# --- NEW CENTRALIZED DATA LOADING LOGIC ---
selected_date = st.session_state.selected_date
selected_year = selected_date.strftime("%Y")
selected_month = selected_date.strftime("%B")
selected_date_str = selected_date.strftime("%Y-%m-%d")

# Only load the dataframes once per date selection
# Using session state to store the dataframes
@st.cache_data(show_spinner="Fetching 24-hour rainfall data from Google Sheets...")
def get_daily_data(date_str, month, year):
    sheet_name = f"24HR_Rainfall_{month}_{year}"
    tab_name = f"master24hrs_{date_str}"
    return load_sheet_data(sheet_name, tab_name)

@st.cache_data(show_spinner="Fetching 2-hour rainfall data from Google Sheets...")
def get_hourly_data(date_str, month, year):
    sheet_name = f"2HR_Rainfall_{month}_{year}"
    tab_name = f"2hrs_master_{date_str}"
    return load_sheet_data(sheet_name, tab_name)

# Load dataframes once at the top level of the app's execution
df_24hr = get_daily_data(selected_date_str, selected_month, selected_year)
df_2hr = get_hourly_data(selected_date_str, selected_month, selected_year)

# We can also load GeoJSON data here once
@st.cache_resource
def load_all_geojson():
    taluka_geojson = load_geojson("gujarat_taluka_clean.geojson")
    district_geojson = load_geojson("gujarat_district_clean.geojson")
    return taluka_geojson, district_geojson

taluka_geojson, district_geojson = load_all_geojson()


# Now, the rest of the app just uses these pre-loaded dataframes
tab_daily, tab_hourly, tab_historical = st.tabs(["Daily Summary", "Hourly Trends", "Historical Data (Coming Soon)"])

with tab_daily:
    st.header("Daily Rainfall Summary")
    if not df_24hr.empty:
        # Pass the pre-loaded geojson files to the dashboard function to avoid reloading
        show_24_hourly_dashboard(df_24hr, selected_date, taluka_geojson, district_geojson)
    else:
        st.warning(f"⚠️ Daily data is not available for {selected_date_str}.")

with tab_hourly:
    st.header("Hourly Rainfall Trends (2-Hourly)")
    if not df_2hr.empty:
        # ... logic for hourly tab, which now uses df_2hr directly ...
        # (The rest of the code in this section would be the same)
    else:
        st.warning(f"⚠️ 2-Hourly data is not available for {selected_date_str}.")

with tab_historical:
    st.header("Historical Rainfall Data")
    st.info("💡 **Coming Soon:** This section will feature monthly/seasonal data, year-on-year comparisons, and long-term trends.")
