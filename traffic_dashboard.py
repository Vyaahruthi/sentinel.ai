import streamlit as st
import pandas as pd
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import plotly.graph_objects as go
from backend.database import get_db_client
import time

st.set_page_config(page_title="Traffic AI Sentinel", layout="wide")

# -------------------- DB INIT --------------------
try:
    client = get_db_client()
except Exception as e:
    st.error(f"Failed to initialize database client: {e}")
    st.stop()

st.title("🚦 Real-Time Traffic Control AI Sentinel")

# -------------------- SIDEBAR --------------------
st.sidebar.header("Controls")

mode = st.sidebar.radio("View Mode", ["Live", "Historical"])

if mode == "Live":
    refresh_rate = st.sidebar.slider("Live Refresh Rate (seconds)", 2, 10, 5)

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
def get_color_for_status(z_score):
    if z_score < 1:
        return "green"
    elif z_score < 2:
        return "orange"
    else:
        return "red"

# -------------------- LIVE MODE --------------------
if mode == "Live":

    st.markdown("### Live Traffic Monitor")

    df_live = fetch_live_decisions(selected_junctions)

    if not df_live.empty:

        cols = st.columns(len(selected_junctions))

        for idx, j in enumerate(selected_junctions):
            j_df = df_live[df_live["junction_id"] == j]

            with cols[idx]:
                st.subheader(f"Junction {j} ({junction_map.get(j)})")

                if not j_df.empty:
                    latest = j_df.iloc[0]

                    z = latest["z_score"]
                    color = get_color_for_status(z)

                    # STATUS
                    if z == 0:
                        st.markdown("**Status:** 🟡 Learning baseline...")
                    else:
                        st.markdown(f"**Status:** :{color}[Z-Score {z:.2f}]")

                    # METRICS
                    c1, c2 = st.columns(2)
                    c1.metric("Traffic", latest["original_traffic"])
                    c2.metric("Lanes", latest["lanes_allocated"])

                    # WHY PANEL
                    with st.expander("Why this decision?"):
                        st.write(f"Z-score: {z:.2f}")
                        st.write(f"Traffic: {latest['original_traffic']}")
                        st.write(f"Lanes: {latest['lanes_allocated']}")
                        st.write(f"Reason: {latest['reason']}")

                else:
                    st.write("No data available.")

        # ---------------- TABLE ----------------
        st.markdown("### Last 50 Decisions")
        df_live["timestamp"] = pd.to_datetime(df_live["timestamp"])
        st.dataframe(
            df_live.sort_values("id", ascending=False),
            use_container_width=True
        )

        # ---------------- GRAPHS ----------------
        st.markdown("### Live Trends")

        df_live = df_live.sort_values("id", ascending=True)

        for j in selected_junctions:
            j_df = df_live[df_live["junction_id"] == j]

            if not j_df.empty:
                st.markdown(f"#### {j} Trends")

                fig = go.Figure()

                fig.add_trace(go.Scatter(
                    x=j_df["timestamp"],
                    y=j_df["original_traffic"],
                    name="Traffic",
                    line=dict(color="blue")
                ))

                fig.add_trace(go.Scatter(
                    x=j_df["timestamp"],
                    y=j_df["z_score"],
                    name="Z-Score",
                    yaxis="y2",
                    line=dict(color="red")
                ))

                fig.add_trace(go.Bar(
                    x=j_df["timestamp"],
                    y=j_df["lanes_allocated"],
                    name="Lanes",
                    marker_color="green",
                    opacity=0.3
                ))

                fig.update_layout(
                    title=f"{j} Activity",
                    yaxis=dict(title="Traffic"),
                    yaxis2=dict(
                        title="Z-Score",
                        overlaying="y",
                        side="right"
                    ),
                    hovermode="x unified"
                )

                st.plotly_chart(fig, use_container_width=True)

    else:
        st.info("No live data available.")

    # ---------------- CONTROLLED REFRESH ----------------
    if "last_refresh" not in st.session_state:
        st.session_state.last_refresh = time.time()

    if time.time() - st.session_state.last_refresh > refresh_rate:
        st.session_state.last_refresh = time.time()
        st.rerun()

# -------------------- HISTORICAL MODE --------------------
elif mode == "Historical":
    st.markdown("### Historical Traffic Data")
    
    # Render with full width in the main window
    date_range = st.date_input("Select a Date Range", [])
    
    if len(date_range) != 2:
        st.info("Select a full date range to view historical data.")
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
            except Exception as e:
                pass
                
        if not data:
            st.warning("No historical decisions data found for the selected date range.")
        else:
            df_hist = pd.DataFrame(data)
            df_hist["timestamp"] = pd.to_datetime(df_hist["timestamp"])
            
            st.markdown(f"### Historical Records ({len(df_hist)} events)")
            st.dataframe(df_hist.sort_values("id", ascending=False), use_container_width=True)
            
            st.markdown("### Historical Trends")
            df_hist = df_hist.sort_values("id", ascending=True)

            for j in selected_junctions:
                j_df = df_hist[df_hist["junction_id"] == j]
                if not j_df.empty:
                    st.markdown(f"#### {j} Historical Activity")
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=j_df["timestamp"], y=j_df.get("original_traffic", j_df.get("traffic", 0)), name="Traffic", line=dict(color="blue")))
                    if "z_score" in j_df.columns:
                        fig.add_trace(go.Scatter(x=j_df["timestamp"], y=j_df["z_score"], name="Z-Score", yaxis="y2", line=dict(color="red")))
                    
                    fig.update_layout(
                        title=f"{j} Traffic Trends",
                        yaxis=dict(title="Traffic"),
                        yaxis2=dict(title="Z-Score", overlaying="y", side="right"),
                        hovermode="x unified"
                    )
                    st.plotly_chart(fig, use_container_width=True)