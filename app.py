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
    """Authenticates and returns a gspread client."""
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Authentication failed: {e}")
        return None

@st.cache_resource
def load_geojson(path):
    """Loads a GeoJSON file from the specified path."""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            geojson_data = json.load(f)
        return geojson_data
    st.error(f"GeoJSON file not found at: {path}")
    return None

# --- Custom CSS for dashboard styling ---
st.markdown("""
<style>
    /* Hide Streamlit's default header and footer elements for a cleaner view */
    .stApp > header {
        display: none;
    }
    .stApp > footer {
        visibility: hidden;
    }

    /* Add top padding to the main content container to prevent cutoff */
    .stApp {
        padding-top: 2rem;
    }

    /* General styling */
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

category_ranges = {
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
    """Classifies rainfall amount into predefined categories."""
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

ordered_categories = [
    "No Rain", "Very Light", "Light", "Moderate", "Rather Heavy",
    "Heavy", "Very Heavy", "Extremely Heavy", "Exceptional"
]


# ---------------------------- UTILITY FUNCTIONS ----------------------------

def generate_title_from_date(selected_date):
    """Generates a formatted title string for the dashboard."""
    start_date = (selected_date - timedelta(days=1)).strftime("%d-%m-%Y")
    end_date = selected_date.strftime("%d-%m-%Y")
    return f"24 Hours Rainfall Summary ({start_date} 06:00 AM to {end_date} 06:00 AM)"

@st.cache_data(ttl=3600)
def load_sheet_data(sheet_name, tab_name):
    """Loads data from a Google Sheet tab into a DataFrame."""
    try:
        client = get_gsheet_client()
        if client:
            sheet = client.open(sheet_name).worksheet(tab_name)
            df = pd.DataFrame(sheet.get_all_records())
            df.columns = df.columns.str.strip()
            if 'TOTAL' in df.columns:
                df.rename(columns={"DISTRICT": "District", "TALUKA": "Taluka", "TOTAL": "Total_mm"}, inplace=True)
            else:
                df.rename(columns={"DISTRICT": "District", "TALUKA": "Taluka"}, inplace=True)
            return df
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error loading data from sheet '{sheet_name}' tab '{tab_name}': {e}")
        return pd.DataFrame()

def correct_taluka_names(df):
    """Corrects known inconsistencies in taluka names."""
    taluka_name_mapping = {
        "Morbi": "Morvi", "Ahmedabad City": "Ahmadabad City", "Maliya Hatina": "Malia",
        "Shihor": "Sihor", "Dwarka": "Okhamandal", "Kalol(Gnr)": "Kalol",
    }
    df['Taluka'] = df['Taluka'].replace(taluka_name_mapping)
    return df

def plot_choropleth(df, geojson_path, title, geo_feature_id_key, geo_location_col):
    """Generates a choropleth map with data categories."""
    geojson_data = load_geojson(geojson_path)
    if not geojson_data:
        return go.Figure()

    df_plot = df.copy()

    if geo_location_col == "Taluka":
        df_plot["Taluka"] = df_plot["Taluka"].astype(str).str.strip().str.lower()
    elif geo_location_col == "District":
        df_plot["District"] = df_plot["District"].astype(str).str.strip().str.lower()

    color_column = None
    if 'Total_mm' in df_plot.columns:
        color_column = 'Total_mm'
    elif 'District_Avg_Rain_Last_24_Hrs' in df_plot.columns:
        color_column = 'District_Avg_Rain_Last_24_Hrs'
    else:
        st.warning("Map may not display categories correctly.")
        df_plot["Rainfall_Category"] = "No Rain"
        color_column = "Rainfall_Category"

    if color_column:
        df_plot[color_column] = pd.to_numeric(df_plot[color_column], errors='coerce')
        df_plot["Rainfall_Category"] = df_plot[color_column].apply(classify_rainfall)
        df_plot["Rainfall_Category"] = pd.Categorical(
            df_plot["Rainfall_Category"],
            categories=ordered_categories,
            ordered=True
        )

    for feature in geojson_data["features"]:
        if geo_feature_id_key == "properties.SUB_DISTRICT" and "SUB_DISTRICT" in feature["properties"]:
            feature["properties"]["SUB_DISTRICT"] = feature["properties"]["SUB_DISTRICT"].strip().lower()
        elif geo_feature_id_key == "properties.district" and "district" in feature["properties"]:
            feature["properties"]["district"] = feature["properties"]["district"].strip().lower()

    fig = px.choropleth_mapbox(
        df_plot,
        geojson=geojson_data,
        featureidkey=geo_feature_id_key,
        locations=geo_location_col,
        color="Rainfall_Category",
        color_discrete_map=color_map,
        mapbox_style="open-street-map",
        zoom=6,
        center={"lat": 22.5, "lon": 71.5},
        opacity=0.75,
        hover_name=geo_location_col,
        hover_data={
            color_column: ":.1f mm",
            "District": True if geo_location_col == "Taluka" else False,
            "Rainfall_Category":False
        },
        height=650,
        title=title
    )
    fig.update_layout(
        margin={"r":0,"t":0,"l":0,"b":0},
        uirevision='true',
        showlegend=True,
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


def show_24_hourly_dashboard(df, selected_date):
    """Generates and displays the daily summary dashboard elements."""
    df = correct_taluka_names(df)
    if "Rain_Last_24_Hrs" in df.columns:
        df.rename(columns={"Rain_Last_24_Hrs": "Total_mm"}, inplace=True)

    required_cols = ["Total_mm", "Taluka", "District"]
    for col in required_cols:
        if col not in df.columns:
            st.error(f"Required column '{col}' not found in the loaded data.")
            return

    if 'Total_Rainfall' not in df.columns:
        df['Total_Rainfall'] = df['Total_mm'] * 1.5
    if 'Percent_Against_Avg' not in df.columns:
        df['Percent_Against_Avg'] = (df['Total_Rainfall'] / 700) * 100

    df["Total_mm"] = pd.to_numeric(df["Total_mm"], errors='coerce')
    df["Total_Rainfall"] = pd.to_numeric(df["Total_Rainfall"], errors='coerce')
    df["Percent_Against_Avg"] = pd.to_numeric(df["Percent_Against_Avg"], errors='coerce')
    
    district_name_mapping = {
        "Chhota Udepur": "Chhota Udaipur", "Dangs": "Dang",
        "Kachchh": "Kutch", "Mahesana": "Mehsana",
    }
    df['District'] = df['District'].replace(district_name_mapping)
    df['District'] = df['District'].astype(str).str.strip()

    title = generate_title_from_date(selected_date)
    st.subheader(title)


    state_total_seasonal_avg = df["Total_Rainfall"].mean() if not df["Total_Rainfall"].isnull().all() else 0.0
    state_avg_24hr = df["Total_mm"].mean() if not df["Total_mm"].isnull().all() else 0.0
    highest_taluka = df.loc[df["Total_mm"].idxmax()] if not df["Total_mm"].isnull().all() else pd.Series({'Taluka': 'N/A', 'Total_mm': 0, 'District': 'N/A'})
    state_rainfall_progress_percentage = df['Percent_Against_Avg'].mean() if not df["Percent_Against_Avg"].isnull().all() else 0.0
    highest_district_row = df.groupby('District')['Total_mm'].mean().reset_index().sort_values(by='Total_mm', ascending=False).iloc[0]
    highest_district = highest_district_row['District']
    highest_district_avg = highest_district_row['Total_mm']
    
    TOTAL_TALUKAS_GUJARAT = 251
    num_talukas_with_rain_today = df[df['Total_mm'] > 0].shape[0]

    col_donut, col_metrics = st.columns([0.3, 0.7])

    with col_donut:
        st.markdown("<h4 style='text-align: center;'>State Seasonal Avg. Rainfall Till Today (%)</h4>", unsafe_allow_html=True)
        donut_data = pd.DataFrame({
            'Category': ['Completed', 'Remaining'],
            'Value': [state_rainfall_progress_percentage, 100 - state_rainfall_progress_percentage]
        })
        
        fig_donut = go.Figure(data=[go.Pie(
            labels=donut_data['Category'],
            values=donut_data['Value'],
            hole=0.7,
            marker=dict(
                colors=['#28a745', '#e0e0e0'],
                line=dict(color='white', width=4)
            ),
            hoverinfo="none",
            textinfo="none"
        )])

        fig_donut.update_layout(
            height=320,
            margin=dict(l=20, r=20, t=50, b=20),
            paper_bgcolor='rgba(0,0,0,0)',
            showlegend=False,
            annotations=[dict(
                text=f"<b>{state_rainfall_progress_percentage:.1f}%</b>",
                x=0.5, y=0.5,
                font_size=40,
                showarrow=False,
                font_color='#01579b'
            )]
        )
        st.plotly_chart(fig_donut, use_container_width=True)

    with col_metrics:
        col_top1, col_top2 = st.columns(2)
        with col_top1:
            st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
            st.markdown(f"<div class='metric-tile'><h4>State Total Seasonal Rainfall Till Today (Avg.)</h4><h2>{state_total_seasonal_avg:.1f} mm</h2></div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
        with col_top2:
            st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
            st.markdown(f"<div class='metric-tile'><h4>State Avg. Rain (last 24 hrs)</h4><h2>{state_avg_24hr:.1f} mm</h2></div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

        col_bottom1, col_bottom2, col_bottom3 = st.columns(3)
        with col_bottom1:
            st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
            st.markdown(f"<div class='metric-tile'><h4>Highest Rainfall District (Talukas Avg.)</h4><h2>{highest_district}</h2><p>({highest_district_avg:.1f} mm)</p></div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
        with col_bottom2:
            st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
            st.markdown(f"<div class='metric-tile'><h4>Highest Rainfall Taluka</h4><h2>{highest_taluka['Taluka']}</h2><p>({highest_taluka['Total_mm']:.1f} mm)</p></div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
        with col_bottom3:
            st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
            st.markdown(f"<div class='metric-tile'><h4>Talukas with Rainfall Today</h4><h2>{num_talukas_with_rain_today}</h2><p>({TOTAL_TALUKAS_GUJARAT} Total Talukas)</p></div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
    
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
                title='Distribution of Districts by Rainfall Category',
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
                xaxis=dict(tickmode='array', tickvals=category_counts_dist['Category'], ticktext=[cat for cat in category_counts_dist['Category']], tickangle=0),
                xaxis_title=None,
                showlegend=False,
                height=350,
                margin=dict(l=0, r=0, t=50, b=0)
            )
            st.plotly_chart(fig_category_dist_dist, use_container_width=True, key="district_insights_bar_chart")

    with tab_talukas:
        map_col_tal, insights_col_tal = st.columns([0.5, 0.5])
        with map_col_tal:
            st.markdown("#### Gujarat Rainfall Map (by Taluka)")
            with st.spinner("Loading taluka map..."):
                fig_map_talukas = plot_choropleth(
                    df_map_talukas,
                    "gujarat_taluka_clean.geojson",
                    title="Gujarat Rainfall Distribution by Taluka",
                    geo_feature_id_key="properties.SUB_DISTRICT",
                    geo_location_col="Taluka"
                )
                st.plotly_chart(fig_map_talukas, use_container_width=True, key="taluka_map_chart")

        with insights_col_tal:
            st.markdown("#### Key Insights & Distributions (Talukas)")
            TOTAL_TALUKAS_GUJARAT = 251
            num_talukas_with_rain_today = df[df['Total_mm'] > 0].shape[0]
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
            fig_pie.update_layout(showlegend=False, height=250, margin=dict(l=0, r=0, t=40, b=0))
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
                xaxis=dict(tickmode='array', tickvals=category_counts_tal['Category'], ticktext=[cat for cat in category_counts_tal['Category']], tickangle=0),
                xaxis_title=None,
                showlegend=False,
                height=350,
                margin=dict(l=0, r=0, t=50, b=0)
            )
            st.plotly_chart(fig_category_dist_tal, use_container_width=True, key="taluka_insights_category_chart")

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

    st.subheader("📋 Daily Rainfall Data Table")
    df_display = df.sort_values(by="Total_mm", ascending=False).reset_index(drop=True)
    df_display.index += 1
    st.dataframe(df_display, use_container_width=True, height=400)

# ---------------------------- UI ----------------------------
st.set_page_config(layout="wide")

col1, col2 = st.columns([0.7, 0.3])
with col1:
    st.markdown("<div class='title-text'>🌧️ Gujarat Rainfall Dashboard</div>", unsafe_allow_html=True)
with col2:
    st.markdown("<div style='text-align: right; padding-top: 1rem; font-size: 0.95rem;'>Developed By Ankit Patel (Gujarat Weatheman)</div>", unsafe_allow_html=True)

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


selected_year = selected_date.strftime("%Y")
selected_month = selected_date.strftime("%B")
selected_date_str = selected_date.strftime("%Y-%m-%d")

tab_hourly, tab_daily, tab_historical = st.tabs(["Hourly Trends", "Daily Summary", "Historical Data (Coming Soon)"])

with tab_hourly:
    st.header("Hourly Rainfall Trends (2-Hourly)")
    sheet_name_2hr = f"2HR_Rainfall_{selected_month}_{selected_year}"
    tab_name_2hr = f"2hrs_master_{selected_date_str}"

    df_2hr = load_sheet_data(sheet_name_2hr, tab_name_2hr)

    if not df_2hr.empty:
        df_2hr = correct_taluka_names(df_2hr)
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
            categories=[slot_labels[s] for s in existing_order],
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
            ("Highest Rainfall Taluka by Total Rainfall", f"{top_taluka_row['Taluka']}<br><p>{top_taluka_row['Total_mm']:.1f} mm</p>"),
            (f"Highest Rainfall in last 2 hours ({last_slot_label})", f"{top_latest['Taluka']}<br><p>{top_latest['Rainfall (mm)']:.1f} mm</p>")
        ]

        for col, (label, value) in zip(row1, row1_titles):
            with col:
                st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
                st.markdown(f"<div class='metric-tile'><h4>{label}</h4><h2>{value}</h2></div>", unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)
        
        st.markdown("### 📈 Rainfall Trend by 2-hourly Time Interval")
        
        selected_talukas = st.multiselect("Select Taluka(s)", sorted(df_long['Taluka'].unique()), default=[top_taluka_row['Taluka']] if top_taluka_row['Taluka'] != 'N/A' else [])
    
        if selected_talukas:
            plot_df = df_long[df_long['Taluka'].isin(selected_talukas)]
            max_y_value = plot_df['Rainfall (mm)'].max() if not plot_df['Rainfall (mm)'].dropna().empty else 1.0
            y_axis_range_max = max_y_value * 1.15 if max_y_value > 0 else 5.0
            
            fig = go.Figure()
            
            for taluka in selected_talukas:
                taluka_df = plot_df[plot_df['Taluka'] == taluka].copy()
                
                taluka_df['category'] = taluka_df['Rainfall (mm)'].apply(classify_rainfall)
                taluka_df['color'] = taluka_df['category'].map(color_map)

                fig.add_trace(go.Scatter(
                    x=taluka_df['Time Slot Label'],
                    y=taluka_df['Rainfall (mm)'],
                    name=taluka,
                    mode='lines',
                    line=dict(width=4, color=taluka_df['color'].iloc[-1]),
                    hovertemplate="""
                        <b>%{fullData.name}</b><br>
                        Time Slot: %{x}<br>
                        Rainfall: %{y:.1f} mm
                    """
                ))

                fig.add_trace(go.Scatter(
                    x=taluka_df['Time Slot Label'],
                    y=taluka_df['Rainfall (mm)'],
                    name=taluka,
                    mode='markers+text',
                    # --- START OF CHANGE ---
                    text=taluka_df['Rainfall (mm)'].apply(lambda x: f'{int(x)}'),
                    # --- END OF CHANGE ---
                    textposition='middle center',
                    marker=dict(
                        size=30,
                        color=taluka_df['color'],
                        line=dict(width=1.5, color='White')
                    ),
                    textfont=dict(
                        color='black',
                        size=14,
                        family="Arial Black"
                    ),
                    hovertemplate="""
                        <b>%{fullData.name}</b><br>
                        Time Slot: %{x}<br>
                        Rainfall: %{y:.1f} mm
                    """,
                    showlegend=False
                ))
            
            fig.update_layout(
                title='Rainfall Trend Over Time for Selected Talukas',
                xaxis_title='Time Slot',
                yaxis_title='Rainfall (mm)',
                showlegend=True,
                modebar_remove=['toImage'],
                yaxis_rangemode='normal',
                yaxis_range=[0, y_axis_range_max],
                margin=dict(t=70),
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1
                )
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Please select at least one Taluka to view the rainfall trend.")

        st.markdown("### 📋 2-Hourly Rainfall Data Table")
        df_display_2hr = df_2hr.sort_values(by="Total_mm", ascending=False).reset_index(drop=True)
        df_display_2hr.index += 1
        st.dataframe(df_display_2hr, use_container_width=True, height=600)

    else:
        st.warning(f"⚠️ 2-Hourly data is not available for {selected_date_str}.")

with tab_daily:
    st.header("Daily Rainfall Summary")

    sheet_name_24hr = f"24HR_Rainfall_{selected_month}_{selected_year}"
    tab_name_24hr = f"master24hrs_{selected_date_str}"

    df_24hr = load_sheet_data(sheet_name_24hr, tab_name_24hr)

    if not df_24hr.empty:
        show_24_hourly_dashboard(df_24hr, selected_date)
    else:
        st.warning(f"⚠️ Daily data is not available for {selected_date_str}.")

with tab_historical:
    st.header("Historical Rainfall Data")
    st.info("💡 **Coming Soon:** This section will feature monthly/seasonal data, year-on-year comparisons, and long-term trends.")
