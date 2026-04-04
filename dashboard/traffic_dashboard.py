import streamlit as st
import pandas as pd
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import plotly.graph_objects as go
from backend.database import get_db_client
import time

# -------------------- PAGE CONFIG --------------------
st.set_page_config(
    page_title="Traffic AI Sentinel",
    page_icon="🚦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -------------------- CUSTOM CSS --------------------
st.markdown("""
<style>
    /* === GLOBAL === */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

    .stApp {
        background: linear-gradient(135deg, #0a0e17 0%, #111827 50%, #0a0e17 100%);
    }

    /* Hide default Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* === SIDEBAR === */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #111827 0%, #0d1117 100%);
        border-right: 1px solid rgba(56, 189, 248, 0.1);
    }
    section[data-testid="stSidebar"] .stMarkdown h2,
    section[data-testid="stSidebar"] .stMarkdown h3 {
        color: #38bdf8 !important;
        font-family: 'Inter', sans-serif;
        font-weight: 600;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        font-size: 0.85rem;
    }
    section[data-testid="stSidebar"] .stRadio label,
    section[data-testid="stSidebar"] .stMultiSelect label,
    section[data-testid="stSidebar"] .stSlider label {
        color: #94a3b8 !important;
        font-family: 'Inter', sans-serif;
    }

    /* === TITLE === */
    .main-title {
        font-family: 'Inter', sans-serif;
        font-weight: 700;
        font-size: 2rem;
        background: linear-gradient(135deg, #38bdf8, #22d3ee, #06b6d4);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        letter-spacing: -0.02em;
        margin-bottom: 0.25rem;
    }
    .main-subtitle {
        font-family: 'Inter', sans-serif;
        font-weight: 400;
        font-size: 0.9rem;
        color: #64748b;
        margin-bottom: 2rem;
    }

    /* === SECTION HEADERS === */
    .section-header {
        font-family: 'Inter', sans-serif;
        font-weight: 600;
        font-size: 1.1rem;
        color: #e2e8f0;
        padding-bottom: 0.75rem;
        margin-bottom: 1rem;
        border-bottom: 1px solid rgba(56, 189, 248, 0.15);
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    .section-header .icon {
        font-size: 1.2rem;
    }

    /* === JUNCTION CARDS === */
    .junction-card {
        background: linear-gradient(145deg, rgba(17, 24, 39, 0.9), rgba(15, 23, 42, 0.95));
        border: 1px solid rgba(56, 189, 248, 0.12);
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 1rem;
        transition: all 0.3s ease;
        position: relative;
        overflow: hidden;
    }
    .junction-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 2px;
        background: linear-gradient(90deg, transparent, #38bdf8, transparent);
        opacity: 0.6;
    }
    .junction-card:hover {
        border-color: rgba(56, 189, 248, 0.3);
        box-shadow: 0 0 30px rgba(56, 189, 248, 0.08);
    }
    .junction-card h3 {
        font-family: 'Inter', sans-serif;
        font-weight: 600;
        font-size: 1rem;
        color: #f1f5f9;
        margin-bottom: 1rem;
    }
    .junction-card .type-badge {
        display: inline-block;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.7rem;
        font-weight: 500;
        color: #38bdf8;
        background: rgba(56, 189, 248, 0.1);
        border: 1px solid rgba(56, 189, 248, 0.2);
        border-radius: 999px;
        padding: 0.15rem 0.6rem;
        margin-left: 0.5rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    /* === STATUS INDICATORS === */
    .status-pill {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.8rem;
        font-weight: 500;
        padding: 0.35rem 0.8rem;
        border-radius: 999px;
        margin-bottom: 1rem;
    }
    .status-green {
        background: rgba(34, 197, 94, 0.12);
        color: #4ade80;
        border: 1px solid rgba(34, 197, 94, 0.25);
    }
    .status-orange {
        background: rgba(251, 191, 36, 0.12);
        color: #fbbf24;
        border: 1px solid rgba(251, 191, 36, 0.25);
    }
    .status-red {
        background: rgba(239, 68, 68, 0.12);
        color: #f87171;
        border: 1px solid rgba(239, 68, 68, 0.25);
    }
    .status-yellow {
        background: rgba(234, 179, 8, 0.12);
        color: #facc15;
        border: 1px solid rgba(234, 179, 8, 0.25);
    }
    .status-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        display: inline-block;
    }
    .status-dot.green { background: #4ade80; box-shadow: 0 0 6px #4ade80; }
    .status-dot.orange { background: #fbbf24; box-shadow: 0 0 6px #fbbf24; }
    .status-dot.red { background: #f87171; box-shadow: 0 0 6px #f87171; }
    .status-dot.yellow { background: #facc15; box-shadow: 0 0 6px #facc15; }

    /* === METRIC CARDS === */
    .metric-row {
        display: flex;
        gap: 0.75rem;
        margin-bottom: 1rem;
    }
    .metric-box {
        flex: 1;
        background: rgba(15, 23, 42, 0.6);
        border: 1px solid rgba(56, 189, 248, 0.08);
        border-radius: 8px;
        padding: 0.75rem;
        text-align: center;
    }
    .metric-label {
        font-family: 'Inter', sans-serif;
        font-size: 0.7rem;
        font-weight: 500;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 0.25rem;
    }
    .metric-value {
        font-family: 'JetBrains Mono', monospace;
        font-size: 1.4rem;
        font-weight: 600;
        color: #f1f5f9;
    }

    /* === WHY PANEL (expander) === */
    .streamlit-expanderHeader {
        background: rgba(15, 23, 42, 0.5) !important;
        border: 1px solid rgba(56, 189, 248, 0.1) !important;
        border-radius: 8px !important;
        color: #94a3b8 !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 0.85rem !important;
    }
    .streamlit-expanderContent {
        background: rgba(15, 23, 42, 0.3) !important;
        border: 1px solid rgba(56, 189, 248, 0.06) !important;
        border-top: none !important;
        border-radius: 0 0 8px 8px !important;
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 0.8rem !important;
        color: #94a3b8 !important;
    }

    /* === DATA TABLE === */
    .stDataFrame {
        border-radius: 12px;
        overflow: hidden;
    }
    .stDataFrame [data-testid="stDataFrameContainer"] {
        border: 1px solid rgba(56, 189, 248, 0.1);
        border-radius: 12px;
    }

    /* === GENERAL TEXT === */
    .stMarkdown p, .stMarkdown li {
        color: #cbd5e1;
        font-family: 'Inter', sans-serif;
    }
    .stMarkdown h3 {
        color: #e2e8f0 !important;
        font-family: 'Inter', sans-serif;
    }
    .stMarkdown h4 {
        color: #94a3b8 !important;
        font-family: 'Inter', sans-serif;
        font-weight: 500;
    }

    /* === INFO / WARNING BOXES === */
    .stAlert {
        background: rgba(15, 23, 42, 0.6) !important;
        border: 1px solid rgba(56, 189, 248, 0.15) !important;
        border-radius: 10px !important;
        color: #94a3b8 !important;
        font-family: 'Inter', sans-serif !important;
    }

    /* === METRICS (native st.metric) === */
    [data-testid="stMetric"] {
        background: rgba(15, 23, 42, 0.6);
        border: 1px solid rgba(56, 189, 248, 0.08);
        border-radius: 10px;
        padding: 0.75rem 1rem;
    }
    [data-testid="stMetricLabel"] {
        font-family: 'Inter', sans-serif !important;
        font-size: 0.75rem !important;
        font-weight: 500 !important;
        color: #64748b !important;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    [data-testid="stMetricValue"] {
        font-family: 'JetBrains Mono', monospace !important;
        font-weight: 600 !important;
        color: #f1f5f9 !important;
    }

    /* === PLOTLY CHARTS CONTAINER === */
    .stPlotlyChart {
        background: rgba(17, 24, 39, 0.5);
        border: 1px solid rgba(56, 189, 248, 0.08);
        border-radius: 12px;
        padding: 0.5rem;
        margin-bottom: 1rem;
    }

    /* === LIVE INDICATOR === */
    .live-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.75rem;
        font-weight: 600;
        color: #4ade80;
        background: rgba(34, 197, 94, 0.1);
        border: 1px solid rgba(34, 197, 94, 0.2);
        border-radius: 999px;
        padding: 0.3rem 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.1em;
    }
    .live-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: #4ade80;
        box-shadow: 0 0 8px #4ade80;
        animation: livePulse 1.5s ease-in-out infinite;
    }
    @keyframes livePulse {
        0%, 100% { opacity: 0.4; box-shadow: 0 0 4px #4ade80; }
        50% { opacity: 1; box-shadow: 0 0 12px #4ade80; }
    }

    /* === DIVIDER === */
    .styled-divider {
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(56, 189, 248, 0.2), transparent);
        margin: 1.5rem 0;
        border: none;
    }
</style>
""", unsafe_allow_html=True)

# -------------------- PLOTLY THEME --------------------
PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Inter, sans-serif", color="#94a3b8", size=12),
    title_font=dict(family="Inter, sans-serif", color="#e2e8f0", size=16),
    xaxis=dict(
        gridcolor="rgba(56, 189, 248, 0.06)",
        zerolinecolor="rgba(56, 189, 248, 0.1)",
        tickfont=dict(family="JetBrains Mono, monospace", size=10, color="#64748b"),
    ),
    yaxis=dict(
        gridcolor="rgba(56, 189, 248, 0.06)",
        zerolinecolor="rgba(56, 189, 248, 0.1)",
        tickfont=dict(family="JetBrains Mono, monospace", size=10, color="#64748b"),
    ),
    legend=dict(
        bgcolor="rgba(0,0,0,0)",
        font=dict(color="#94a3b8", size=11),
    ),
    margin=dict(l=50, r=50, t=50, b=40),
    hoverlabel=dict(
        bgcolor="#1e293b",
        bordercolor="rgba(56, 189, 248, 0.3)",
        font=dict(family="JetBrains Mono, monospace", color="#f1f5f9", size=12),
    ),
)

CHART_COLORS = {
    "traffic": "#38bdf8",
    "z_score": "#f87171",
    "lanes": "#4ade80",
}

# -------------------- DB INIT --------------------
try:
    client = get_db_client()
except Exception as e:
    st.error(f"Failed to initialize database client: {e}")
    st.stop()

# -------------------- HEADER --------------------
st.markdown('<h1 class="main-title">🚦 Traffic AI Sentinel</h1>', unsafe_allow_html=True)
st.markdown('<p class="main-subtitle">Real-time intelligent traffic monitoring & adaptive lane control</p>', unsafe_allow_html=True)

# -------------------- SIDEBAR --------------------
st.sidebar.markdown("### ⚙️ Controls")

mode = st.sidebar.radio("View Mode", ["Live", "Historical"], label_visibility="collapsed")

if mode == "Live":
    st.sidebar.markdown('<div class="styled-divider"></div>', unsafe_allow_html=True)
    refresh_rate = st.sidebar.slider("Refresh Interval (s)", 2, 10, 5)

st.sidebar.markdown('<div class="styled-divider"></div>', unsafe_allow_html=True)

junctions = ["J1", "J2", "J3"]
selected_junctions = st.sidebar.multiselect("Junctions", junctions, default=junctions)

junction_map = {
    "J1": "Highway",
    "J2": "Intersection",
    "J3": "Roundabout"
}

# -------------------- DATA FETCH --------------------
@st.cache_data(ttl=1)
def fetch_live_decisions(junctions_list):
    data = []
    for j in junctions_list:
        res = client.table("decisions")\
            .select("*")\
            .eq("junction_id", j)\
            .order("id", desc=True)\
            .limit(50)\
            .execute()
        data.extend(res.data)
    return pd.DataFrame(data)

# -------------------- HELPERS --------------------
def get_status_html(z_score):
    if z_score == 0:
        return '<span class="status-pill status-yellow"><span class="status-dot yellow"></span> Calibrating</span>'
    elif z_score < 1:
        return f'<span class="status-pill status-green"><span class="status-dot green"></span> Normal · Z={z_score:.2f}</span>'
    elif z_score < 2:
        return f'<span class="status-pill status-orange"><span class="status-dot orange"></span> Elevated · Z={z_score:.2f}</span>'
    else:
        return f'<span class="status-pill status-red"><span class="status-dot red"></span> Critical · Z={z_score:.2f}</span>'

def render_junction_card(latest, junction_id, junction_type):
    z = latest["z_score"]
    status_html = get_status_html(z)
    return f"""
    <div class="junction-card">
        <h3>{junction_id} <span class="type-badge">{junction_type}</span></h3>
        {status_html}
        <div class="metric-row">
            <div class="metric-box">
                <div class="metric-label">Traffic</div>
                <div class="metric-value">{latest['original_traffic']}</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">Lanes</div>
                <div class="metric-value">{latest['lanes_allocated']}</div>
            </div>
        </div>
    </div>
    """

def create_trend_chart(j_df, junction_id):
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=j_df["timestamp"],
        y=j_df["original_traffic"],
        name="Traffic",
        line=dict(color=CHART_COLORS["traffic"], width=2),
        fill="tozeroy",
        fillcolor="rgba(56, 189, 248, 0.05)",
    ))

    fig.add_trace(go.Scatter(
        x=j_df["timestamp"],
        y=j_df["z_score"],
        name="Z-Score",
        yaxis="y2",
        line=dict(color=CHART_COLORS["z_score"], width=2, dash="dot"),
    ))

    fig.add_trace(go.Bar(
        x=j_df["timestamp"],
        y=j_df["lanes_allocated"],
        name="Lanes",
        marker_color=CHART_COLORS["lanes"],
        opacity=0.2,
    ))

    layout = {**PLOTLY_LAYOUT}
    layout.update(
        title=f"{junction_id} Activity",
        yaxis=dict(title="Traffic", **PLOTLY_LAYOUT["yaxis"]),
        yaxis2=dict(
            title="Z-Score",
            overlaying="y",
            side="right",
            gridcolor="rgba(0,0,0,0)",
            tickfont=dict(family="JetBrains Mono, monospace", size=10, color="#64748b"),
        ),
        hovermode="x unified",
    )
    fig.update_layout(**layout)
    return fig


# ==================== LIVE MODE ====================
if mode == "Live":
    st.markdown(
        '<div class="section-header"><span class="icon">📡</span> Live Monitor '
        '<span class="live-badge"><span class="live-dot"></span> LIVE</span></div>',
        unsafe_allow_html=True
    )

    df_live = fetch_live_decisions(selected_junctions)

    if not df_live.empty:
        # Junction cards
        cols = st.columns(len(selected_junctions))
        for idx, j in enumerate(selected_junctions):
            j_df = df_live[df_live["junction_id"] == j]
            with cols[idx]:
                if not j_df.empty:
                    latest = j_df.iloc[0]
                    st.markdown(
                        render_junction_card(latest, j, junction_map.get(j, "")),
                        unsafe_allow_html=True
                    )
                    with st.expander("💡 Why this decision?"):
                        st.markdown(f"**Z-Score:** `{latest['z_score']:.2f}`")
                        st.markdown(f"**Traffic:** `{latest['original_traffic']}`")
                        st.markdown(f"**Lanes:** `{latest['lanes_allocated']}`")
                        st.markdown(f"**Reason:** {latest['reason']}")
                else:
                    st.info("No data for this junction.")

        # Divider
        st.markdown('<div class="styled-divider"></div>', unsafe_allow_html=True)

        # Table
        st.markdown(
            '<div class="section-header"><span class="icon">📋</span> Recent Decisions</div>',
            unsafe_allow_html=True
        )
        df_live["timestamp"] = pd.to_datetime(df_live["timestamp"])
        st.dataframe(
            df_live.sort_values("id", ascending=False),
            use_container_width=True
        )

        # Divider
        st.markdown('<div class="styled-divider"></div>', unsafe_allow_html=True)

        # Charts
        st.markdown(
            '<div class="section-header"><span class="icon">📈</span> Live Trends</div>',
            unsafe_allow_html=True
        )
        df_live = df_live.sort_values("id", ascending=True)

        for j in selected_junctions:
            j_df = df_live[df_live["junction_id"] == j]
            if not j_df.empty:
                fig = create_trend_chart(j_df, j)
                st.plotly_chart(fig, use_container_width=True)

    else:
        st.info("No live data available. Waiting for traffic events...")

    # Controlled refresh
    if "last_refresh" not in st.session_state:
        st.session_state.last_refresh = time.time()

    if time.time() - st.session_state.last_refresh > refresh_rate:
        st.session_state.last_refresh = time.time()
        st.rerun()

# ==================== HISTORICAL MODE ====================
elif mode == "Historical":
    st.markdown(
        '<div class="section-header"><span class="icon">🕐</span> Historical Analysis</div>',
        unsafe_allow_html=True
    )

    date_range = st.date_input("Select Date Range", [])

    if len(date_range) != 2:
        st.info("Select a start and end date to view historical data.")
    else:
        from datetime import timedelta
        start_date, end_date = date_range
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = (end_date + timedelta(days=1)).strftime("%Y-%m-%d")

        data = []
        for j in selected_junctions:
            try:
                res = client.table("decisions")\
                    .select("*")\
                    .eq("junction_id", j)\
                    .gte("timestamp", start_str)\
                    .lt("timestamp", end_str)\
                    .order("id", desc=True)\
                    .limit(1000)\
                    .execute()
                if hasattr(res, 'data') and res.data:
                    data.extend(res.data)
            except Exception:
                pass

        if not data:
            st.warning("No historical data found for the selected range.")
        else:
            df_hist = pd.DataFrame(data)
            df_hist["timestamp"] = pd.to_datetime(df_hist["timestamp"])

            st.markdown(
                f'<div class="section-header"><span class="icon">📋</span> '
                f'Records — {len(df_hist)} events</div>',
                unsafe_allow_html=True
            )
            st.dataframe(
                df_hist.sort_values("id", ascending=False),
                use_container_width=True
            )

            st.markdown('<div class="styled-divider"></div>', unsafe_allow_html=True)

            st.markdown(
                '<div class="section-header"><span class="icon">📈</span> Historical Trends</div>',
                unsafe_allow_html=True
            )
            df_hist = df_hist.sort_values("id", ascending=True)

            for j in selected_junctions:
                j_df = df_hist[df_hist["junction_id"] == j]
                if not j_df.empty:
                    fig = go.Figure()
                    traffic_col = "original_traffic" if "original_traffic" in j_df.columns else "traffic"
                    fig.add_trace(go.Scatter(
                        x=j_df["timestamp"],
                        y=j_df.get(traffic_col, 0),
                        name="Traffic",
                        line=dict(color=CHART_COLORS["traffic"], width=2),
                        fill="tozeroy",
                        fillcolor="rgba(56, 189, 248, 0.05)",
                    ))
                    if "z_score" in j_df.columns:
                        fig.add_trace(go.Scatter(
                            x=j_df["timestamp"],
                            y=j_df["z_score"],
                            name="Z-Score",
                            yaxis="y2",
                            line=dict(color=CHART_COLORS["z_score"], width=2, dash="dot"),
                        ))

                    layout = {**PLOTLY_LAYOUT}
                    layout.update(
                        title=f"{j} Historical Trends",
                        yaxis=dict(title="Traffic", **PLOTLY_LAYOUT["yaxis"]),
                        yaxis2=dict(
                            title="Z-Score",
                            overlaying="y",
                            side="right",
                            gridcolor="rgba(0,0,0,0)",
                            tickfont=dict(family="JetBrains Mono, monospace", size=10, color="#64748b"),
                        ),
                        hovermode="x unified",
                    )
                    fig.update_layout(**layout)
                    st.plotly_chart(fig, use_container_width=True)
