import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from db import client
import time

st.set_page_config(page_title="SENTINEL.AI Dashboard", layout="wide", page_icon="🤖")

st.title("🤖 SENTINEL.AI Monitoring System")

# Sidebar
st.sidebar.header("Sentinel Controls")
mode = st.sidebar.radio("View", ["Live Monitor", "Timeline Replay"])
junctions = ["J1", "J2", "J3"]
selected_junctions = st.sidebar.multiselect("Select Junctions", junctions, default=["J1"])

def fetch_sentinel_data(limit=200):
    if not selected_junctions:
        return pd.DataFrame()
    res = client.table("drift_events")\
        .select("*")\
        .in_("junction_id", selected_junctions)\
        .order("detected_at", desc=True)\
        .limit(limit * len(selected_junctions) * 9)\
        .execute()
    return pd.DataFrame(res.data)

# ✅ FIXED
def get_tier_color(tier):
    if tier == 1:
        return "green"
    elif tier == 2:
        return "orange"
    else:
        return "red"

if mode == "Live Monitor":
    st.subheader("Live Drift & Behaviour Parameters")
    
    df = fetch_sentinel_data(limit=10)
    if not df.empty:
        df["detected_at"] = pd.to_datetime(df["detected_at"])
        df = df.sort_values("detected_at", ascending=False)
        
        for j in selected_junctions:
            st.markdown(f"### Junction: {j}")
            j_df = df[df["junction_id"] == j]
            if not j_df.empty:
                
                latest_time = j_df["detected_at"].iloc[0]
                latest_df = j_df[j_df["detected_at"] == latest_time]
                
                # ✅ FIXED (use z_score for drift strength)
                combined_score = latest_df["z_score"].abs().mean()
                dominant_tier = latest_df.sort_values(["z_score"], ascending=False).iloc[0]["tier"]
                
                c1, c2, c3 = st.columns(3)
                c1.metric("Combined Drift Score", f"{combined_score:.3f}")
                c2.markdown(f"**Dominant Tier (SOS Phase):** :{get_tier_color(dominant_tier)}[{dominant_tier}]")
                c3.markdown(f"**Parameters Analysed:** {len(latest_df)}")
                
                st.markdown("#### The 9 Behavioral Parameters")
                
                cols = st.columns(3)
                for idx, row in latest_df.reset_index(drop=True).iterrows():
                    col_idx = idx % 3
                    with cols[col_idx]:
                        z_col = "red" if abs(row["z_score"]) > 2 else "orange" if abs(row["z_score"]) > 1 else "green"
                        st.markdown(f"""
                        <div style='padding: 10px; border-radius: 5px; border: 1px solid #333; margin-bottom: 10px;'>
                            <b>{row['parameter']}</b><br/>
                            Value: {row['current_value']:.2f} | Conf: {row['confidence']:.2f}<br/>
                            Z-Score: <span style='color:{z_col}'>{row['z_score']:.2f}</span><br/>
                            <i>{row['reason']}</i>
                        </div>
                        """, unsafe_allow_html=True)
                
                st.divider()

        # ✅ FIXED GRAPH
        st.subheader("Parameter Drift (Recent Graph)")
        hist_df = fetch_sentinel_data(limit=50)
        if not hist_df.empty:
            hist_df["detected_at"] = pd.to_datetime(hist_df["detected_at"])
            fig = px.line(
                hist_df,
                x="detected_at",
                y="z_score",   # ✅ FIXED
                color="parameter",
                facet_row="junction_id",
                title="Z-Score Fluctuations across Parameters"
            )
            fig.update_layout(height=600)
            st.plotly_chart(fig, use_container_width=True)

        st.button("Manual Refresh")
        
    else:
        st.info("No data available yet. Ensure Sentinel-AI daemon is running.")

elif mode == "Timeline Replay":
    st.subheader("Timeline Replay")
    df = fetch_sentinel_data(limit=200)
    
    if not df.empty:
        df["detected_at"] = pd.to_datetime(df["detected_at"])
        df = df.sort_values("detected_at")
        
        timestamps = df["detected_at"].dt.strftime('%H:%M:%S').unique()
        
        if len(timestamps) > 0:
            selected_t = st.select_slider("Replay Timestamp", options=timestamps, value=timestamps[-1])
            st.markdown(f"**Viewing data for:** {selected_t}")
            
            replay_df = df[df["detected_at"].dt.strftime('%H:%M:%S') == selected_t]
            
            if not replay_df.empty:
                st.dataframe(
                    replay_df[["junction_id", "parameter", "current_value", "z_score", "confidence", "tier", "reason"]],
                    use_container_width=True
                )
                
                st.subheader("Combined Score Over Time")

                # ✅ FIXED
                combined_df = df.groupby(['detected_at', 'junction_id'])['z_score'].mean().reset_index()

                fig = px.area(
                    combined_df,
                    x="detected_at",
                    y="z_score",   # ✅ FIXED
                    color="junction_id",
                    title="Average Drift (Z-score) Across Parameters"
                )
                
                target_dt = replay_df["detected_at"].iloc[0]
                fig.add_vline(x=target_dt, line_width=2, line_dash="dash", line_color="red")
                
                st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No historical data to replay.")