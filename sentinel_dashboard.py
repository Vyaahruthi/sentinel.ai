"""
Sentinel.AI Dashboard — full 6-tab monitoring interface.
Run: streamlit run sentinel_dashboard.py
"""
import io
import math
import json
import time
import unicodedata
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st
from datetime import datetime, timezone, timedelta
from fpdf import FPDF

from sentinel_db import get_client

st.set_page_config(page_title="Sentinel.AI", layout="wide", page_icon="🛡")
client = get_client()

JUNCTIONS = ["J1", "J2", "J3"]

PARAM_LABELS = {
    "behaviour_adaptation":  "Behaviour Adaptation",
    "data_bias":             "Data Bias",
    "data_drift":            "Data Drift",
    "feedback_loop":         "Feedback Loop",
    "silent_drift":          "Silent Drift",
    "infrastructure_change": "Infrastructure Change",
    "policy_change":         "Policy Change",
    "technology_influence":  "Technology Influence",
    "event_traffic":         "Event Traffic",
}

PARAM_DESCRIPTIONS = {
    "behaviour_adaptation":  "Rate of AI decision changes per tick",
    "data_bias":             "Systematic skew vs long-term mean (σ)",
    "data_drift":            "Log variance ratio recent vs historical",
    "feedback_loop":         "Max consecutive identical lane decisions",
    "silent_drift":          "CUSUM score — slow accumulating drift",
    "infrastructure_change": "Step-change magnitude between data halves (σ)",
    "policy_change":         "Decoupling of decisions from traffic (0=normal, 1=full)",
    "technology_influence":  "Outlier + gap rate — data quality score",
    "event_traffic":         "Event-driven traffic intensity score",
}

TIER_COLORS = {0: "green", 1: "blue", 2: "orange", 3: "red"}
TIER_LABELS = {0: "Normal", 1: "T1 — AI", 2: "T2 — Review", 3: "T3 — SOS"}
TIER_ICONS  = {0: "🟢", 1: "🔵", 2: "🟠", 3: "🔴"}


def _conf(z: float) -> float:
    return round(min(100 * (1 - math.exp(-0.35 * abs(z))), 99.5), 1)

def _tier(z: float) -> int:
    az = abs(z)
    if az >= 3.5: return 3
    if az >= 2.5: return 2
    if az >= 1.5: return 1
    return 0

def _snap(raw) -> dict:
    if isinstance(raw, str):
        try: return json.loads(raw)
        except: return {}
    return raw or {}


# ─── Sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🛡 Sentinel.AI")
    st.caption("Connected to traffic-ai")
    st.divider()
    view = st.radio("View", [
        "Overview",
        "Parameter Drilldown",
        "Drift Timeline",
        "Combination Alerts",
        "Autonomy Panel",
        "Audit Log",
    ])
    st.divider()
    jsel         = st.selectbox("Junction", JUNCTIONS)
    refresh_rate = st.slider("Refresh (sec)", 3, 30, 5)
    auto_refresh = st.checkbox("Auto-refresh", value=True)
    st.divider()
    st.caption(f"Last render: {datetime.now().strftime('%H:%M:%S')}")


# ─── Data fetchers ────────────────────────────────────────────────────────────
def obs(jid, limit=300):
    try:
        res = client.table("sentinel_observations").select("*").eq("junction_id", jid).order("timestamp", desc=True).limit(limit).execute()
        df = pd.DataFrame(res.data or [])
        if not df.empty: df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df
    except: return pd.DataFrame()

def drift_events(jid=None, limit=100):
    try:
        q = client.table("drift_events").select("*").order("detected_at", desc=True).limit(limit)
        if jid: q = q.eq("junction_id", jid)
        df = pd.DataFrame(q.execute().data or [])
        if not df.empty: df["detected_at"] = pd.to_datetime(df["detected_at"])
        return df
    except: return pd.DataFrame()

def baselines(jid):
    try:
        res = client.table("sentinel_baselines").select("*").eq("junction_id", jid).order("computed_at", desc=True).execute()
        df = pd.DataFrame(res.data or [])
        if not df.empty: df = df.groupby("parameter").first().reset_index()
        return df
    except: return pd.DataFrame()

def timeline(jid, param=None):
    try:
        q = client.table("drift_memory").select("*").eq("junction_id", jid).order("recorded_at", desc=False)
        if param: q = q.eq("parameter", param)
        df = pd.DataFrame(q.execute().data or [])
        if not df.empty: df["recorded_at"] = pd.to_datetime(df["recorded_at"])
        return df
    except: return pd.DataFrame()

def combos(jid=None):
    try:
        q = client.table("combination_alerts").select("*").order("detected_at", desc=True).limit(100)
        if jid: q = q.eq("junction_id", jid)
        df = pd.DataFrame(q.execute().data or [])
        if not df.empty: df["detected_at"] = pd.to_datetime(df["detected_at"])
        return df
    except: return pd.DataFrame()

def pending_reviews():
    try:
        df = pd.DataFrame(
            client.table("autonomy_log").select("*").eq("status","pending").order("created_at", desc=True).limit(50).execute().data or []
        )
        if not df.empty: df["created_at"] = pd.to_datetime(df["created_at"])
        return df
    except: return pd.DataFrame()

def autonomy_history():
    try:
        df = pd.DataFrame(
            client.table("autonomy_log").select("*").order("created_at", desc=True).limit(300).execute().data or []
        )
        if not df.empty: df["created_at"] = pd.to_datetime(df["created_at"])
        return df
    except: return pd.DataFrame()

def resolved_drift_events(jid=None, limit=500):
    """Return drift_events with status 'resolved' or 'acknowledged'."""
    try:
        q = (client.table("drift_events")
             .select("*")
             .in_("status", ["resolved", "acknowledged"])
             .order("detected_at", desc=True)
             .limit(limit))
        if jid:
            q = q.eq("junction_id", jid)
        df = pd.DataFrame(q.execute().data or [])
        if not df.empty:
            df["detected_at"] = pd.to_datetime(df["detected_at"])
            if "resolved_at" in df.columns:
                df["resolved_at"] = pd.to_datetime(df["resolved_at"])
        return df
    except:
        return pd.DataFrame()

def reviewed_autonomy_log(jid=None, limit=500):
    """Return autonomy_log entries that are 'reviewed' (human acted on them)."""
    try:
        q = (client.table("autonomy_log")
             .select("*")
             .eq("status", "reviewed")
             .order("reviewed_at", desc=True)
             .limit(limit))
        if jid:
            q = q.eq("junction_id", jid)
        df = pd.DataFrame(q.execute().data or [])
        if not df.empty:
            df["created_at"]  = pd.to_datetime(df["created_at"])
            df["reviewed_at"] = pd.to_datetime(df["reviewed_at"])
        return df
    except:
        return pd.DataFrame()

# ─── PDF generator ────────────────────────────────────────────────────────────
def _safe(text) -> str:
    """Strip/replace characters that fpdf latin-1 can't encode."""
    if text is None:
        return ""
    s = str(text)
    # Normalise unicode to closest ASCII equivalent where possible
    s = unicodedata.normalize("NFKD", s).encode("latin-1", errors="replace").decode("latin-1")
    return s

def generate_audit_pdf(
    drift_df: pd.DataFrame,
    autonomy_df: pd.DataFrame,
    junction_filter: str,
    tier_filter,
    date_from,
    date_to,
    generated_by: str,
) -> bytes:
    """Build and return a PDF audit report as bytes."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # ── Cover / header ─────────────────────────────────────────────────────
    pdf.set_fill_color(30, 30, 50)
    pdf.rect(0, 0, 210, 40, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_xy(10, 10)
    pdf.cell(0, 10, "SENTINEL.AI  -  Audit Log Report", ln=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_xy(10, 23)
    pdf.cell(0, 6,
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}  "
        f"| By: {_safe(generated_by) or 'System'}  "
        f"| Junction: {junction_filter}  "
        f"| Period: {date_from} to {date_to}",
        ln=True,
    )
    pdf.set_text_color(0, 0, 0)
    pdf.ln(15)

    # ── Summary stats ──────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Executive Summary", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_fill_color(240, 242, 250)

    total_drift   = len(drift_df)
    total_auto    = len(autonomy_df)
    t1 = len(drift_df[drift_df["tier"] == 1]) if not drift_df.empty else 0
    t2 = len(drift_df[drift_df["tier"] == 2]) if not drift_df.empty else 0
    t3 = len(drift_df[drift_df["tier"] == 3]) if not drift_df.empty else 0

    stats = [
        ("Total alerts (resolved/acknowledged)", total_drift),
        ("  - Tier 1 (AI auto-resolved)",        t1),
        ("  - Tier 2 (Human review)",             t2),
        ("  - Tier 3 (SOS)",                      t3),
        ("Total autonomy decisions reviewed",     total_auto),
    ]
    for label, val in stats:
        pdf.cell(130, 7, _safe(label), border=0, fill=True)
        pdf.cell( 40, 7, str(val),      border=0, fill=True, align="R")
        pdf.ln(7)
    pdf.ln(5)

    # ── Drift Event Details ────────────────────────────────────────────────
    if not drift_df.empty:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, f"Drift Events  ({len(drift_df)} records)", ln=True)
        pdf.ln(2)

        # Table header
        col_widths = [28, 12, 36, 14, 14, 14, 22, 30, 26]
        headers    = ["Detected At", "Jxn", "Parameter", "Z-score", "Conf%",
                      "Tier", "Status", "Reason", "Resolved At"]
        pdf.set_fill_color(50, 60, 100)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 7)
        for w, h in zip(col_widths, headers):
            pdf.cell(w, 8, h, border=1, fill=True, align="C")
        pdf.ln()
        pdf.set_text_color(0, 0, 0)

        for idx, (_, row) in enumerate(drift_df.iterrows()):
            fill = idx % 2 == 0
            pdf.set_fill_color(245, 246, 252) if fill else pdf.set_fill_color(255, 255, 255)
            pdf.set_font("Helvetica", "", 7)
            det_at = str(row.get("detected_at", ""))[:19]
            res_at = str(row.get("resolved_at", ""))[:19] if pd.notna(row.get("resolved_at")) else "—"
            param  = PARAM_LABELS.get(row.get("parameter", ""), row.get("parameter", ""))
            vals   = [
                _safe(det_at),
                _safe(row.get("junction_id", "")),
                _safe(param),
                _safe(f"{row.get('z_score', 0):.2f}"),
                _safe(f"{row.get('confidence', 0):.1f}"),
                _safe(str(row.get("tier", ""))),
                _safe(row.get("status", "")),
                _safe(str(row.get("reason", ""))[:38]),
                _safe(res_at),
            ]
            for w, v in zip(col_widths, vals):
                pdf.cell(w, 7, v, border=1, fill=fill, align="L")
            pdf.ln()
        pdf.ln(6)

    # ── Autonomy / Human Decision Log ──────────────────────────────────────
    if not autonomy_df.empty:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, f"Autonomy Decision Log  ({len(autonomy_df)} records)", ln=True)
        pdf.ln(2)

        # Table header
        col_widths2 = [28, 12, 10, 36, 14, 30, 26, 26, 28]
        headers2    = ["Created At", "Jxn", "Tier", "AI Decision", "AI Conf%",
                       "Human Decision", "Reviewer", "Reviewed At", "Notes"]
        pdf.set_fill_color(50, 100, 60)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 7)
        for w, h in zip(col_widths2, headers2):
            pdf.cell(w, 8, h, border=1, fill=True, align="C")
        pdf.ln()
        pdf.set_text_color(0, 0, 0)

        for idx, (_, row) in enumerate(autonomy_df.iterrows()):
            fill = idx % 2 == 0
            pdf.set_fill_color(245, 252, 246) if fill else pdf.set_fill_color(255, 255, 255)
            pdf.set_font("Helvetica", "", 7)
            rev_at = str(row.get("reviewed_at", ""))[:19] if pd.notna(row.get("reviewed_at")) else "—"
            vals2  = [
                _safe(str(row.get("created_at", ""))[:19]),
                _safe(row.get("junction_id", "")),
                _safe(str(row.get("tier", ""))),
                _safe(str(row.get("ai_decision", ""))[:38]),
                _safe(f"{row.get('ai_confidence', 0) or 0:.1f}"),
                _safe(str(row.get("human_decision", ""))[:28]),
                _safe(str(row.get("human_reviewer", ""))[:22]),
                _safe(rev_at),
                _safe(str(row.get("notes", ""))[:26]),
            ]
            for w, v in zip(col_widths2, vals2):
                pdf.cell(w, 7, v, border=1, fill=fill, align="L")
            pdf.ln()
        pdf.ln(6)

    # ── Footer ─────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 6,
        "SENTINEL.AI Audit Report  -  Confidential  -  For authorised personnel only",
        align="C", ln=True,
    )

    return bytes(pdf.output())


# ═══════════════════════════════════════════════════════════════════════════════
# OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════════
if view == "Overview":
    st.title("🛡 Sentinel.AI — Overview")

    # Junction status row
    cols = st.columns(3)
    for i, jid in enumerate(JUNCTIONS):
        de    = drift_events(jid, limit=50)
        active = de[de["status"]=="active"] if not de.empty else pd.DataFrame()
        mtier  = int(active["tier"].max()) if not active.empty else 0
        tc     = TIER_COLORS[mtier]
        with cols[i]:
            st.markdown(f"### {jid}")
            st.markdown(f"**Status:** :{tc}[{TIER_ICONS[mtier]} {TIER_LABELS[mtier]}]")
            st.metric("Active drifts", len(active))
            if not active.empty:
                for _, r in active.head(4).iterrows():
                    st.markdown(
                        f"<small>• **{PARAM_LABELS.get(r['parameter'],r['parameter'])}** "
                        f"z={r.get('z_score',0):.2f} conf={r.get('confidence',0):.0f}% "
                        f"T{r['tier']}</small>", unsafe_allow_html=True
                    )

    st.divider()

    # Z-score heatmap across all junctions
    st.subheader("Z-score heatmap — all junctions × all parameters")
    rows = []
    for jid in JUNCTIONS:
        o  = obs(jid, limit=200)
        bl = baselines(jid)
        if o.empty or bl.empty: continue
        latest = o.groupby("parameter").first().reset_index()
        for _, r in latest.iterrows():
            b = bl[bl["parameter"]==r["parameter"]]
            if b.empty: continue
            mean = b.iloc[0]["mean"]
            std  = max(b.iloc[0]["std"], 1e-9)
            z    = (r["value"] - mean) / std
            rows.append({"Junction": jid,
                         "Parameter": PARAM_LABELS.get(r["parameter"], r["parameter"]),
                         "Z-score": round(z, 2)})
    if rows:
        hdf = pd.DataFrame(rows).pivot(index="Parameter", columns="Junction", values="Z-score")
        fig = px.imshow(hdf, color_continuous_scale="RdYlGn_r",
                        zmin=-4, zmax=4, text_auto=".1f", aspect="auto")
        fig.update_layout(height=380, margin=dict(l=10,r=10,t=10,b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Heatmap appears once sentinel has built up baseline data (~20 ticks per parameter).")

    # Recent drift events table
    st.subheader("Recent drift events")
    all_de = drift_events(limit=40)
    if not all_de.empty:
        all_de["Parameter"] = all_de["parameter"].map(lambda x: PARAM_LABELS.get(x,x))
        st.dataframe(
            all_de[["detected_at","junction_id","Parameter","z_score","confidence","tier","reason","status"]].head(25),
            use_container_width=True, height=280
        )
    else:
        st.info("No drift events yet.")

    if auto_refresh:
        time.sleep(refresh_rate)
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# PARAMETER DRILLDOWN
# ═══════════════════════════════════════════════════════════════════════════════
elif view == "Parameter Drilldown":
    st.title(f"🔬 Parameter Drilldown — {jsel}")

    param = st.selectbox("Select parameter",
                         list(PARAM_LABELS.keys()),
                         format_func=lambda x: PARAM_LABELS[x])
    st.caption(PARAM_DESCRIPTIONS.get(param, ""))

    o  = obs(jsel, limit=300)
    bl = baselines(jsel)

    if o.empty or bl.empty:
        st.warning("No data yet — make sure sentinel_main.py is running.")
    else:
        po  = o[o["parameter"]==param]
        row = bl[bl["parameter"]==param]

        if po.empty or row.empty:
            st.info(f"Baseline not yet computed for {PARAM_LABELS[param]}. "
                    f"Needs ~20 observations.")
        else:
            mean = row.iloc[0]["mean"]
            std  = max(row.iloc[0]["std"], 1e-9)
            cv   = float(po.iloc[0]["value"])
            z    = (cv - mean) / std
            conf = _conf(z)
            tier = _tier(z)
            tc   = TIER_COLORS[tier]

            # ── Metrics row ──────────────────────────────────────────────────
            c1,c2,c3,c4,c5 = st.columns(5)
            c1.metric("Current value",  f"{cv:.4f}")
            c2.metric("Baseline mean",  f"{mean:.4f}")
            c3.metric("Baseline std",   f"{std:.4f}")
            c4.metric("Z-score",        f"{z:+.3f}")
            c5.metric("Confidence",     f"{conf:.1f}%")
            st.markdown(f"**Tier:** :{tc}[{TIER_ICONS[tier]} {TIER_LABELS[tier]}]")

            # Latest reason
            de = drift_events(jsel, limit=50)
            if not de.empty:
                pe = de[de["parameter"]==param]
                if not pe.empty:
                    r = pe.iloc[0].get("reason","")
                    if r: st.info(f"**Reason:** {r}")

            st.divider()

            # ── Value vs baseline + tier thresholds ──────────────────────────
            pts = po.sort_values("timestamp").copy()
            pts["z_ts"] = (pts["value"] - mean) / std

            fig1 = go.Figure()
            fig1.add_trace(go.Scatter(x=pts["timestamp"], y=pts["value"],
                name="Observed", line=dict(color="#378ADD", width=2)))
            fig1.add_hline(y=mean,           line_dash="dash",  line_color="#639922",
                           annotation_text=f"Baseline ({mean:.4f})")
            for y_off, color, label in [
                (1.5,"#378ADD","T1+"), (2.5,"#BA7517","T2+"), (3.5,"#E24B4A","T3+"),
                (-1.5,"#378ADD",None), (-2.5,"#BA7517",None), (-3.5,"#E24B4A",None),
            ]:
                kw = {"annotation_text": label} if label else {}
                fig1.add_hline(y=mean+y_off*std, line_dash="dot",
                               line_color=color, **kw)
            fig1.update_layout(
                title=f"{PARAM_LABELS[param]} — value with dynamic thresholds",
                height=300, margin=dict(l=40,r=40,t=40,b=20))
            st.plotly_chart(fig1, use_container_width=True)

            # ── Z-score over time ─────────────────────────────────────────────
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(x=pts["timestamp"], y=pts["z_ts"],
                name="Z-score", line=dict(color="#7F77DD", width=2),
                fill="tozeroy", fillcolor="rgba(127,119,221,0.07)"))
            for y, color, label in [(1.5,"#378ADD","T1"),(2.5,"#BA7517","T2"),(3.5,"#E24B4A","T3")]:
                fig2.add_hline(y= y, line_dash="dot", line_color=color, annotation_text=label)
                fig2.add_hline(y=-y, line_dash="dot", line_color=color)
            fig2.add_hline(y=0, line_color="#639922", line_width=1)
            fig2.update_layout(title="Z-score over time",
                               height=240, margin=dict(l=40,r=40,t=40,b=20))
            st.plotly_chart(fig2, use_container_width=True)

            # ── Gauge + distribution side by side ────────────────────────────
            g_col, d_col = st.columns(2)

            with g_col:
                gauge_color = ("#E24B4A" if conf>70 else
                               "#BA7517" if conf>40 else "#639922")
                fig3 = go.Figure(go.Indicator(
                    mode="gauge+number",
                    value=conf,
                    title={"text": "Drift confidence %"},
                    gauge={
                        "axis":  {"range": [0,100]},
                        "bar":   {"color": gauge_color},
                        "steps": [
                            {"range":[0,40],  "color":"#EAF3DE"},
                            {"range":[40,70], "color":"#FAEEDA"},
                            {"range":[70,100],"color":"#FCEBEB"},
                        ],
                    }
                ))
                fig3.update_layout(height=260, margin=dict(l=20,r=20,t=40,b=10))
                st.plotly_chart(fig3, use_container_width=True)

            with d_col:
                x_rng   = np.linspace(mean-4.5*std, mean+4.5*std, 300)
                bl_pdf  = (1/(std*np.sqrt(2*np.pi))) * np.exp(-0.5*((x_rng-mean)/std)**2)
                fig4 = go.Figure()
                fig4.add_trace(go.Histogram(x=pts["value"].values,
                    histnorm="probability density", nbinsx=25,
                    name="Observed", opacity=0.55, marker_color="#378ADD"))
                fig4.add_trace(go.Scatter(x=x_rng, y=bl_pdf,
                    name="Baseline", line=dict(color="#639922", width=2, dash="dash")))
                fig4.add_vline(x=cv, line_color="#E24B4A",
                               annotation_text=f"Current ({cv:.3f})")
                fig4.update_layout(title="Baseline vs observed distribution",
                    height=260, margin=dict(l=20,r=20,t=40,b=20), barmode="overlay")
                st.plotly_chart(fig4, use_container_width=True)

            # ── Raw context of latest observation ────────────────────────────
            ctx_raw = po.iloc[0].get("raw_context", {})
            ctx     = _snap(ctx_raw)
            if ctx:
                st.subheader("Latest observation context")
                ctx_df = pd.DataFrame([{"Key": k, "Value": v} for k,v in ctx.items()])
                st.dataframe(ctx_df, use_container_width=True, hide_index=True)

    if auto_refresh:
        time.sleep(refresh_rate)
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# DRIFT TIMELINE REPLAY
# ═══════════════════════════════════════════════════════════════════════════════
elif view == "Drift Timeline":
    st.title(f"📼 Drift Timeline Replay — {jsel}")

    col_a, col_b = st.columns(2)
    with col_a:
        pf = st.selectbox("Filter parameter",
            ["All"]+list(PARAM_LABELS.keys()),
            format_func=lambda x: "All parameters" if x=="All" else PARAM_LABELS.get(x,x))
    with col_b:
        days_back = st.slider("Look back (days)", 1, 30, 7)

    tl = timeline(jsel, None if pf=="All" else pf)

    if tl.empty:
        st.info("No drift memory yet. Let sentinel run for a few minutes.")
    else:
        cutoff = pd.Timestamp.utcnow() - pd.Timedelta(days=days_back)
        tl     = tl[tl["recorded_at"]>cutoff].copy()
        tl["z_abs"]   = tl["snapshot"].apply(lambda s: abs(_snap(s).get("z_score") or 0))
        tl["tier_val"] = tl["snapshot"].apply(lambda s: _snap(s).get("tier") or 0)
        tl["p_label"]  = tl["parameter"].map(lambda x: PARAM_LABELS.get(x,x))

        st.markdown(f"**{len(tl)} memory entries** in the last {days_back} days")

        # Scatter timeline
        fig = px.scatter(
            tl, x="recorded_at", y="p_label",
            color="memory_type",
            size=(tl["z_abs"]+0.3).clip(0.3, 6),
            color_discrete_map={
                "onset":      "#E24B4A",
                "peak":       "#A32D2D",
                "resolution": "#639922"
            },
            hover_data=["z_abs","tier_val","memory_type"],
            title="Drift memory — size = |Z|  |  red=onset  darkred=peak  green=resolution"
        )
        fig.update_layout(height=420, margin=dict(l=40,r=40,t=40,b=20))
        st.plotly_chart(fig, use_container_width=True)

        # Z-score over memory timeline (line chart per parameter)
        if pf != "All":
            fig2 = go.Figure()
            for mtype, color in [("onset","#E24B4A"),("peak","#A32D2D"),("resolution","#639922")]:
                sub = tl[tl["memory_type"]==mtype]
                if not sub.empty:
                    fig2.add_trace(go.Scatter(
                        x=sub["recorded_at"], y=sub["z_abs"],
                        mode="markers+lines", name=mtype,
                        line=dict(color=color), marker=dict(size=8)
                    ))
            for y, color, label in [(1.5,"#378ADD","T1"),(2.5,"#BA7517","T2"),(3.5,"#E24B4A","T3")]:
                fig2.add_hline(y=y, line_dash="dot", line_color=color, annotation_text=label)
            fig2.update_layout(title=f"|Z-score| over time — {PARAM_LABELS.get(pf,pf)}",
                               height=260, margin=dict(l=40,r=40,t=40,b=20))
            st.plotly_chart(fig2, use_container_width=True)

        # Step-through replay
        st.subheader("Step-through replay")
        if len(tl) > 0:
            idx  = st.slider("Memory entry", 0, max(len(tl)-1,0), 0)
            entry = tl.iloc[idx]
            snap  = _snap(entry.get("snapshot"))

            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Parameter",   PARAM_LABELS.get(entry.get("parameter",""),
                                                       entry.get("parameter","")))
            c2.metric("Memory type", str(entry.get("memory_type","")).upper())
            c3.metric("Z-score",     str(snap.get("z_score","—")))
            c4.metric("Confidence",  f"{snap.get('confidence','—')}%")

            tier_v = snap.get("tier", 0)
            tc     = TIER_COLORS.get(tier_v, "green")
            st.markdown(f"**Tier at this moment:** :{tc}[{TIER_ICONS.get(tier_v,'?')} {TIER_LABELS.get(tier_v,'—')}]")
            st.markdown(f"**Current value:** {snap.get('current_value','—')}")
            st.markdown(f"**Baseline mean:** {snap.get('baseline_mean','—')}")
            st.markdown(f"**Reason:** {snap.get('reason','—')}")
            st.caption(f"Recorded at: {str(entry.get('recorded_at',''))[:19]}")


# ═══════════════════════════════════════════════════════════════════════════════
# COMBINATION ALERTS
# ═══════════════════════════════════════════════════════════════════════════════
elif view == "Combination Alerts":
    st.title("⚡ Combination Drift Alerts")

    all_c = combos()
    junc_c = combos(jsel)

    c1,c2,c3 = st.columns(3)
    c1.metric("Total combination alerts",    len(all_c))
    c2.metric(f"Alerts for {jsel}",          len(junc_c))
    if not all_c.empty:
        c3.metric("Highest escalated tier",  int(all_c["escalated_tier"].max()))

    st.divider()

    if junc_c.empty:
        st.success(f"No combination alerts for {jsel}. "
                   f"System requires 3+ simultaneous parameter drifts to trigger one.")
    else:
        for _, row in junc_c.head(20).iterrows():
            params_list = row.get("parameters", [])
            if isinstance(params_list, str):
                try: params_list = json.loads(params_list)
                except: params_list = []
            z_map = _snap(row.get("individual_z_scores", {}))
            tier  = row.get("escalated_tier", 1)
            tc    = TIER_COLORS.get(tier, "green")

            with st.expander(
                f"{TIER_ICONS.get(tier,'?')} "
                f"{str(row.get('detected_at',''))[:19]}  |  "
                f"Tier {tier}  |  {len(params_list)} parameters"
            ):
                st.markdown(f"**Escalated tier:** :{tc}[{TIER_LABELS.get(tier,tier)}]")
                st.markdown(f"**Combined Z-score:** {row.get('combined_score','—')}")
                st.markdown(f"**Reason:** {row.get('reason','')}")

                if z_map:
                    labels = [PARAM_LABELS.get(p,p) for p in z_map]
                    zvals  = list(z_map.values())
                    bar_colors = [
                        "#E24B4A" if abs(z)>=3.5 else
                        "#BA7517" if abs(z)>=2.5 else
                        "#378ADD" for z in zvals
                    ]
                    fig = go.Figure(go.Bar(
                        x=labels, y=zvals,
                        marker_color=bar_colors,
                        text=[f"{z:.2f}" for z in zvals],
                        textposition="outside"
                    ))
                    for y, color, label in [(1.5,"#378ADD","T1"),(2.5,"#BA7517","T2"),(3.5,"#E24B4A","T3")]:
                        fig.add_hline(y=y, line_dash="dot", line_color=color,
                                      annotation_text=label)
                    fig.update_layout(
                        title="Individual Z-scores in this combination",
                        height=280, margin=dict(l=20,r=20,t=40,b=80)
                    )
                    st.plotly_chart(fig, use_container_width=True)

    if auto_refresh:
        time.sleep(refresh_rate)
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# AUTONOMY PANEL
# ═══════════════════════════════════════════════════════════════════════════════
elif view == "Autonomy Panel":
    st.title("🤖 Tiered Autonomy Panel")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.info("**Tier 1 — AI only**\n\n"
                "Drift logged automatically. "
                "AI continues operating. No human action needed.")
    with col2:
        st.warning("**Tier 2 — Human + AI**\n\n"
                   "Significant drift. AI generates a recommended action "
                   "but will NOT execute it until a human approves or overrides.")
    with col3:
        st.error("**Tier 3 — SOS**\n\n"
                 "Critical drift. Automated control suspended. "
                 "Human must respond immediately.")

    st.divider()
    sub = st.radio("", ["Pending reviews", "All history"], horizontal=True)

    if sub == "Pending reviews":
        pr = pending_reviews()
        if pr.empty:
            st.success("No pending reviews — system operating autonomously.")
        else:
            st.warning(f"{len(pr)} pending review(s) awaiting human decision")
            for _, row in pr.iterrows():
                tier = row.get("tier", 1)
                icon = TIER_ICONS.get(tier, "?")
                with st.expander(
                    f"{icon} [{TIER_LABELS.get(tier)}]  "
                    f"{row.get('junction_id','')}  "
                    f"|  {str(row.get('created_at',''))[:19]}"
                ):
                    st.markdown(f"**AI decision:** {row.get('ai_decision','')}")
                    st.markdown(f"**AI confidence:** {row.get('ai_confidence',0):.1f}%")
                    st.markdown(f"**Context:** {row.get('notes','')}")
                    st.divider()
                    with st.form(key=f"form_{row['id']}"):
                        decision = st.selectbox("Your decision",
                            ["APPROVE","OVERRIDE","ESCALATE_TO_T3"])
                        reviewer = st.text_input("Reviewer name / ID")
                        notes_in = st.text_area("Notes (optional)")
                        if st.form_submit_button("Submit review"):
                            if reviewer:
                                try:
                                    client.table("autonomy_log").update({
                                        "human_decision": decision,
                                        "human_reviewer": reviewer,
                                        "reviewed_at":    datetime.now(timezone.utc).isoformat(),
                                        "status":         "reviewed",
                                        "notes":          notes_in,
                                    }).eq("id", row["id"]).execute()
                                    st.success("Review submitted.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Failed to submit: {e}")
                            else:
                                st.error("Reviewer name is required.")

    else:  # All history
        ah = autonomy_history()
        if ah.empty:
            st.info("No autonomy history yet.")
        else:
            tier_counts = ah["tier"].value_counts().to_dict()
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Total events",    len(ah))
            c2.metric("T1 — AI auto",   tier_counts.get(1,0))
            c3.metric("T2 — Review",    tier_counts.get(2,0))
            c4.metric("T3 — SOS",       tier_counts.get(3,0))

            fig = px.histogram(
                ah, x="created_at", color="tier",
                color_discrete_map={1:"#378ADD", 2:"#BA7517", 3:"#E24B4A"},
                title="Autonomy events over time by tier",
                nbins=40
            )
            fig.update_layout(height=280, margin=dict(l=40,r=40,t=40,b=20))
            st.plotly_chart(fig, use_container_width=True)

            show_cols = [c for c in [
                "created_at","junction_id","tier","ai_decision",
                "ai_confidence","status","human_decision","human_reviewer"
            ] if c in ah.columns]
            st.dataframe(ah[show_cols], use_container_width=True, height=400)

    if auto_refresh:
        time.sleep(refresh_rate)
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT LOG
# ═══════════════════════════════════════════════════════════════════════════════
elif view == "Audit Log":
    st.title("📋 Audit Log — Resolved & Acknowledged Alerts")
    st.caption(
        "This view lists every drift event that has been resolved or acknowledged, "
        "and every autonomy decision that has received a human review. "
        "Use the filters below, then click **Download PDF** to export a signed audit report."
    )

    # ── Filters ───────────────────────────────────────────────────────────────
    st.subheader("Filters")
    fc1, fc2, fc3, fc4 = st.columns([2, 2, 2, 2])
    with fc1:
        audit_junc = st.selectbox("Junction", ["All"] + JUNCTIONS, key="audit_junc")
    with fc2:
        audit_tiers = st.multiselect(
            "Tier", [1, 2, 3],
            default=[1, 2, 3],
            format_func=lambda t: TIER_LABELS.get(t, str(t)),
            key="audit_tiers",
        )
    with fc3:
        audit_date_from = st.date_input(
            "From date",
            value=(datetime.now() - timedelta(days=30)).date(),
            key="audit_date_from",
        )
    with fc4:
        audit_date_to = st.date_input(
            "To date",
            value=datetime.now().date(),
            key="audit_date_to",
        )

    generated_by = st.text_input(
        "Report generated by (name / ID)",
        placeholder="e.g. Prashant V.",
        key="audit_gen_by",
    )

    # ── Fetch data ────────────────────────────────────────────────────────────
    _junc_filter = None if audit_junc == "All" else audit_junc
    raw_drift    = resolved_drift_events(jid=_junc_filter)
    raw_auto     = reviewed_autonomy_log(jid=_junc_filter)

    # Date filtering
    if not raw_drift.empty:
        raw_drift = raw_drift[
            (raw_drift["detected_at"].dt.date >= audit_date_from) &
            (raw_drift["detected_at"].dt.date <= audit_date_to)
        ]
    if not raw_auto.empty:
        raw_auto = raw_auto[
            (raw_auto["created_at"].dt.date >= audit_date_from) &
            (raw_auto["created_at"].dt.date <= audit_date_to)
        ]

    # Tier filtering
    if audit_tiers and not raw_drift.empty:
        raw_drift = raw_drift[raw_drift["tier"].isin(audit_tiers)]

    # ── Summary metrics ───────────────────────────────────────────────────────
    st.divider()
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Resolved / Ack. alerts", len(raw_drift))
    m2.metric("Tier 1 resolved",  len(raw_drift[raw_drift["tier"] == 1]) if not raw_drift.empty else 0)
    m3.metric("Tier 2 resolved",  len(raw_drift[raw_drift["tier"] == 2]) if not raw_drift.empty else 0)
    m4.metric("Tier 3 resolved",  len(raw_drift[raw_drift["tier"] == 3]) if not raw_drift.empty else 0)
    m5.metric("Human reviews logged", len(raw_auto))

    st.divider()

    # ── Drift Events Table ────────────────────────────────────────────────────
    st.subheader(f"🔵 Resolved / Acknowledged Drift Events  ({len(raw_drift)})")
    if raw_drift.empty:
        st.info("No resolved or acknowledged drift events match the selected filters.")
    else:
        disp_drift = raw_drift.copy()
        disp_drift["Parameter"] = disp_drift["parameter"].map(
            lambda x: PARAM_LABELS.get(x, x)
        )
        disp_drift["Tier"] = disp_drift["tier"].map(
            lambda t: f"{TIER_ICONS.get(t, '')} {TIER_LABELS.get(t, t)}"
        )
        show_cols_drift = [c for c in [
            "detected_at", "junction_id", "Parameter",
            "z_score", "confidence", "Tier", "status",
            "reason", "resolved_at",
        ] if c in disp_drift.columns or c in ["Parameter", "Tier"]]
        st.dataframe(
            disp_drift[show_cols_drift].rename(columns={
                "detected_at":  "Detected At",
                "junction_id":  "Junction",
                "z_score":      "Z-score",
                "confidence":   "Confidence %",
                "status":       "Status",
                "reason":       "Reason",
                "resolved_at":  "Resolved At",
            }),
            use_container_width=True,
            height=320,
        )

    st.divider()

    # ── Autonomy Log Table ────────────────────────────────────────────────────
    st.subheader(f"🟢 Human-Reviewed Autonomy Decisions  ({len(raw_auto)})")
    if raw_auto.empty:
        st.info("No reviewed autonomy decisions match the selected filters.")
    else:
        show_cols_auto = [c for c in [
            "created_at", "junction_id", "tier",
            "ai_decision", "ai_confidence",
            "human_decision", "human_reviewer",
            "reviewed_at", "notes",
        ] if c in raw_auto.columns]
        st.dataframe(
            raw_auto[show_cols_auto].rename(columns={
                "created_at":      "Created At",
                "junction_id":     "Junction",
                "tier":            "Tier",
                "ai_decision":     "AI Decision",
                "ai_confidence":   "AI Conf %",
                "human_decision":  "Human Decision",
                "human_reviewer":  "Reviewer",
                "reviewed_at":     "Reviewed At",
                "notes":           "Notes",
            }),
            use_container_width=True,
            height=280,
        )

    st.divider()

    # ── PDF Download ──────────────────────────────────────────────────────────
    st.subheader("📥 Download PDF Audit Report")

    if raw_drift.empty and raw_auto.empty:
        st.warning(
            "No data to export. Adjust your filters or wait for alerts to be resolved."
        )
    else:
        if st.button("Generate & Download PDF", type="primary", key="gen_pdf_btn"):
            with st.spinner("Building PDF report..."):
                try:
                    pdf_bytes = generate_audit_pdf(
                        drift_df       = raw_drift,
                        autonomy_df    = raw_auto,
                        junction_filter= audit_junc,
                        tier_filter    = audit_tiers,
                        date_from      = audit_date_from,
                        date_to        = audit_date_to,
                        generated_by   = generated_by,
                    )
                    fname = (
                        f"sentinel_audit_"
                        f"{audit_junc.replace(' ','_')}_"
                        f"{audit_date_from}_to_{audit_date_to}.pdf"
                    )
                    st.download_button(
                        label        = "⬇ Click here to save the PDF",
                        data         = pdf_bytes,
                        file_name    = fname,
                        mime         = "application/pdf",
                        key          = "pdf_download_btn",
                    )
                    st.success(
                        f"PDF generated successfully! "
                        f"{len(raw_drift)} drift events + "
                        f"{len(raw_auto)} autonomy decisions included."
                    )
                except Exception as e:
                    st.error(f"PDF generation failed: {e}")
