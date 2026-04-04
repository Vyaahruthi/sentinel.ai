import streamlit as st
import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go
import datetime
import io

# ── Page config — must be first Streamlit call ──────────────────────────────
st.set_page_config(
    page_title="Sentinel AI Monitoring",
    layout="wide",
    page_icon="👁️"
)

API_URL = "http://127.0.0.1:8000"

# ---------------------------------------------------------------------------
# Constants & Mappings
# ---------------------------------------------------------------------------

SEVERITY_MAP = {
    "behaviour_adaptation": "High",
    "data_bias":            "Medium",
    "data_drift":           "High",
    "feedback_loop":        "High",
    "silent_drift":         "Medium",
    "infrastructure_change":"Low",
    "policy_change":        "Medium",
    "technology_influence": "Medium",
    "event_traffic":        "Low",
}

SEVERITY_COLORS = {
    "High":   "#ef4444",
    "Medium": "#f59e0b",
    "Low":    "#22c55e",
}

METRIC_LABELS = {
    "behaviour_adaptation": "Behaviour Adaptation (slope)",
    "data_bias":            "Data Bias (gap)",
    "data_drift":           "Data Drift (diff)",
    "feedback_loop":        "Feedback Loop (corr)",
    "silent_drift":         "Silent Drift (slope)",
    "infrastructure_change":"Infrastructure Change (var)",
    "policy_change":        "Policy Change (shift)",
    "technology_influence": "Technology Influence (spikes)",
    "event_traffic":        "Event Traffic (count)",
}

METRIC_KEYS = list(METRIC_LABELS.keys())

# ---------------------------------------------------------------------------
# Safe API helpers — never crash the page
# ---------------------------------------------------------------------------

def safe_get(endpoint: str, timeout: int = 5) -> dict | None:
    """GET from API. Returns parsed JSON or None on any failure."""
    try:
        r = requests.get(f"{API_URL}{endpoint}", timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def safe_post(endpoint: str, payload: dict, timeout: int = 5) -> dict | None:
    """POST to API. Returns parsed JSON or None on any failure."""
    try:
        r = requests.post(f"{API_URL}{endpoint}", json=payload, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Flatten metrics — sentinel_engine returns {junction_id: {metric: val}}
# We merge all junctions into one flat dict by averaging
# ---------------------------------------------------------------------------

def flatten_metrics(raw_metrics: dict) -> dict:
    """
    Accepts either:
      - Flat dict:  {"behaviour_adaptation": 0.003, ...}
      - Nested dict: {"J1": {"behaviour_adaptation": 0.003}, "J2": {...}}
    Returns flat dict of metric_key -> float.
    """
    if not raw_metrics:
        return {}

    # Check if already flat (values are numbers not dicts)
    first_val = next(iter(raw_metrics.values()), None)
    if isinstance(first_val, (int, float)):
        return raw_metrics

    # Nested: average across junctions
    merged = {}
    counts = {}
    for junction_data in raw_metrics.values():
        if not isinstance(junction_data, dict):
            continue
        for k, v in junction_data.items():
            if isinstance(v, (int, float)):
                merged[k] = merged.get(k, 0.0) + v
                counts[k] = counts.get(k, 0) + 1
    return {k: merged[k] / counts[k] for k in merged}


def flatten_z_scores(raw_z: dict) -> dict:
    """Same flattening logic for z_scores nested by junction."""
    if not raw_z:
        return {}
    first_val = next(iter(raw_z.values()), None)
    if not isinstance(first_val, dict):
        return raw_z
    merged = {}
    counts = {}
    for jdata in raw_z.values():
        if not isinstance(jdata, dict):
            continue
        for k, v in jdata.items():
            if isinstance(v, (int, float)):
                merged[k] = merged.get(k, 0.0) + v
                counts[k] = counts.get(k, 0) + 1
    return {k: merged[k] / counts[k] for k in merged}


def flatten_baseline_mean(raw_mean: dict) -> dict:
    """Same flattening logic for baseline_mean nested by junction."""
    if not raw_mean:
        return {}
    first_val = next(iter(raw_mean.values()), None)
    if not isinstance(first_val, dict):
        return raw_mean
    merged = {}
    counts = {}
    for jdata in raw_mean.values():
        if not isinstance(jdata, dict):
            continue
        for k, v in jdata.items():
            if isinstance(v, (int, float)):
                merged[k] = merged.get(k, 0.0) + v
                counts[k] = counts.get(k, 0) + 1
    return {k: merged[k] / counts[k] for k in merged}


# ---------------------------------------------------------------------------
# Plain-English translation
# ---------------------------------------------------------------------------

def get_translation(key: str, value: float) -> str:
    v = abs(value)
    translations = {
        "behaviour_adaptation": [
            (0.001, "Decision thresholds are stable. No adaptation detected."),
            (0.01,  "Minor adaptation in decision logic. Within acceptable range."),
            (float('inf'), "The AI is making decisions differently than it was trained to. Human review recommended."),
        ],
        "silent_drift": [
            (0.02, "Decision pattern is consistent over recent history."),
            (0.05, "Gradual shift in decision pattern detected. Monitor closely."),
            (float('inf'), "Significant silent drift. The AI's decision boundary has moved without any retraining."),
        ],
        "data_bias": [
            (0.5, "Input data distribution matches baseline. No bias detected."),
            (1.0, "Moderate gap between current inputs and training distribution."),
            (float('inf'), "Current inputs are significantly outside the training data range. AI decisions may be unreliable."),
        ],
        "feedback_loop": [
            (0.4,  "Operator overrides are not correlated with drift. System is self-consistent."),
            (0.75, "Some correlation between human overrides and drift. Possible feedback effect forming."),
            (float('inf'), "Strong feedback loop detected. Frequent human overrides may be reinforcing drift."),
        ],
        "infrastructure_change": [
            (0.1, "Infrastructure is stable."),
            (float('inf'), "Infrastructure variance is high. Environmental changes may be influencing AI behaviour."),
        ],
        "data_drift": [
            (10.0, "Input data is within the expected range."),
            (30.0, "Moderate drift in input data distribution detected."),
            (float('inf'), "Significant data drift. Model may be operating on unfamiliar inputs."),
        ],
        "policy_change": [
            (0.05, "No policy changes detected."),
            (0.15, "Minor policy shift observed."),
            (float('inf'), "Significant policy change. Verify intended behaviour."),
        ],
        "technology_influence": [
            (2.0, "No unusual technology influence."),
            (4.0, "Some app routing influence detected."),
            (float('inf'), "Significant technology-driven spikes affecting AI decisions."),
        ],
        "event_traffic": [
            (5.0, "Event traffic is within normal range."),
            (8.0, "Elevated event-driven traffic."),
            (float('inf'), "High event traffic. AI decisions may be skewed by event patterns."),
        ],
    }
    buckets = translations.get(key, [])
    for threshold, text in buckets:
        if v < threshold:
            return text
    return "No interpretation available."


# ---------------------------------------------------------------------------
# Metric card renderer
# ---------------------------------------------------------------------------

def render_metric_card(
    label: str, key: str, value: float,
    z_score: float = None, mean: float = None,
    is_stable: bool = True, learning: bool = False,
    fmt: str = ".4f"
):
    st.metric(label, f"{value:{fmt}}")
    translation = get_translation(key, value)

    if learning or z_score is None:
        z_str = '<span style="color:#94a3b8;">Z-score: Calibrating...</span>'
    else:
        z_abs = abs(z_score)
        if z_abs < 2.0:
            z_str = f'<span style="color:#94a3b8;">Z-score: {z_score:+.2f} [Within normal range]</span>'
        elif z_abs < 2.3:
            z_str = f'<span style="color:#f59e0b;">Z-score: {z_score:+.2f} [Elevated — Tier 1]</span>'
        elif z_abs < 3.0:
            z_str = f'<span style="color:#f97316;">Z-score: {z_score:+.2f} [Anomaly — Tier 2]</span>'
        else:
            z_str = f'<span style="color:#ef4444; font-weight:bold;">Z-score: {z_score:+.2f} [Critical — Tier 3 SOS 🚨]</span>'

    warning_icon = (
        " <span title='Unstable baseline' style='color:#f59e0b;'>⚠️</span>"
        if not is_stable and not learning else ""
    )
    mean_str = (
        f"Baseline mean: {mean:{fmt}}{warning_icon}"
        if mean is not None else "Baseline mean: Calibrating..."
    )

    st.markdown(f"""
    <div style="margin-top:-10px; margin-bottom:16px;">
        <div style="font-size:13px; font-family:monospace; margin-bottom:4px;">{z_str}</div>
        <div style="font-size:12px; color:#64748b; margin-bottom:4px;">{mean_str}</div>
        <div style="color:#94a3b8; font-size:12px; line-height:1.4;">{translation}</div>
    </div>
    """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Alert resolution helper
# ---------------------------------------------------------------------------

def resolve_alert(alert_type: str, status: str, notes: str = ""):
    safe_post("/resolve", {
        "alert_type": alert_type,
        "status":     status,
        "notes":      notes,
    })
    st.session_state.resolved_types.add(alert_type)
    if alert_type in st.session_state.active_alerts:
        del st.session_state.active_alerts[alert_type]


def _derive_action(status: str) -> str:
    mapping = {
        "RESOLVED":      "Resolved",
        "ACKNOWLEDGED":  "Acknowledged",
        "FALSE_POSITIVE":"Marked False Positive",
        "ESCALATED":     "Escalated to MLOps",
        "OVERRIDDEN":    "Manual Override",
    }
    return mapping.get(status, "Pending")


# ---------------------------------------------------------------------------
# PDF generation — safe, no external dependency on jinja
# ---------------------------------------------------------------------------

def generate_audit_pdf(rows: list, metrics: dict) -> bytes:
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=letter)
        styles = getSampleStyleSheet()
        elements = []

        elements.append(Paragraph("SENTINEL.AI — Audit Report", styles["Title"]))
        elements.append(Paragraph(
            f"Generated: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            styles["Normal"]
        ))
        elements.append(Spacer(1, 12))

        headers = ["Alert ID", "Type", "Severity", "Description", "Created", "Status"]
        data = [headers]
        for r in rows:
            a_type = r.get("alert_type") or "—"
            data.append([
                str(r.get("id", ""))[:8],
                a_type,
                SEVERITY_MAP.get(a_type, "Medium"),
                (r.get("alert_text") or "—")[:60],
                (r.get("resolved_at") or "—")[:19],
                r.get("status", "—"),
            ])

        t = Table(data, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND",  (0, 0), (-1, 0), colors.HexColor("#1e293b")),
            ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
            ("FONTSIZE",    (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("GRID",        (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ]))
        elements.append(t)
        doc.build(elements)
        return buf.getvalue()
    except Exception:
        # Fallback: return minimal text PDF bytes if reportlab not installed
        return b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/MediaBox[0 0 612 792]>>endobj\nxref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000058 00000 n\n0000000115 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF"


# ---------------------------------------------------------------------------
# Session state initialisation — safe, never crashes
# ---------------------------------------------------------------------------

if "active_alerts" not in st.session_state:
    st.session_state.active_alerts = {}

if "resolved_types" not in st.session_state:
    st.session_state.resolved_types = set()
    data = safe_get("/resolutions")
    if data:
        st.session_state.resolved_types = {
            r["alert_type"] for r in data.get("resolved_alerts", [])
            if r.get("alert_type") and r.get("status") in (
                "RESOLVED", "ACKNOWLEDGED", "FALSE_POSITIVE"
            )
        }

if "audit_page" not in st.session_state:
    st.session_state.audit_page = 0

if "sim_results" not in st.session_state:
    st.session_state.sim_results = None

# ---------------------------------------------------------------------------
# Auto-refresh — after session state, before any rendering
# ---------------------------------------------------------------------------

try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=5000, key="sentinel_refresh")
except ImportError:
    pass  # dashboard still works, just without auto-refresh

# ===========================================================================
# FETCH DATA — all in one place, all safe
# ===========================================================================

sentinel_data = safe_get("/metrics") or {}
logs_data     = safe_get("/logs") or {}
logs          = logs_data.get("logs", []) if isinstance(logs_data, dict) else []

# Parse sentinel response
mode           = sentinel_data.get("mode", "unknown")
status         = sentinel_data.get("status", "unknown")
raw_metrics    = sentinel_data.get("metrics", {})
raw_z_scores   = sentinel_data.get("z_scores", {})
alerts_list    = sentinel_data.get("alerts", [])
baseline_info  = sentinel_data.get("baseline", {})
raw_mean       = baseline_info.get("mean", {})

metrics  = raw_metrics
z_scores = raw_z_scores
baseline_mean = raw_mean

learning = (mode == "baseline_learning")
run_count = baseline_info.get("run_count", 0)
learning_progress = baseline_info.get("learning_progress", 0)
baseline_quality  = baseline_info.get("quality", {})

# ===========================================================================
# TITLE
# ===========================================================================

st.title("👁️ Sentinel AI: Behaviour Monitoring & Explanations")

# ===========================================================================
# API CONNECTION CHECK — shown only when API is unreachable
# ===========================================================================

if not sentinel_data:
    st.error(
        "⚠️ Cannot reach the Sentinel API at `http://127.0.0.1:8000`. "
        "Make sure your FastAPI backend is running (`uvicorn main:app --reload`) "
        "and that the `/sentinel-status` endpoint exists."
    )
    st.info(
        "The dashboard will auto-retry every 5 seconds. "
        "Check your terminal for backend errors."
    )
    st.stop()

# ===========================================================================
# BASELINE LEARNING BANNER
# ===========================================================================

if learning:
    st.warning(
        f"🔄 **Building baseline — {run_count}/30 evaluation runs complete.** "
        f"Sentinel is learning what normal looks like for this system. "
        f"No alerts will fire during this phase."
    )
    st.progress(min(learning_progress / 100, 1.0))
    st.info(
        f"Progress: {learning_progress}% — Once 30 runs are complete, "
        f"Z-score based alerting activates automatically."
    )

elif mode == "active":
    col_s1, col_s2, col_s3 = st.columns(3)
    col_s1.success("✅ Baseline locked — active monitoring")
    col_s2.metric("Evaluation runs", run_count)

    sos_active = any(a.get("tier") == 3 for a in alerts_list)
    tier2_count = sum(1 for a in alerts_list if a.get("tier") == 2)
    tier1_count = sum(1 for a in alerts_list if a.get("tier") == 1)

    if sos_active:
        col_s3.error("🚨 SOS — Human required")
    elif tier2_count:
        col_s3.warning(f"⚠️ {tier2_count} alert(s) awaiting human review")
    else:
        col_s3.success("✅ System operating normally")

# ===========================================================================
# SECTION 1 — CRITICAL DRIFT ALERTS (always shown when alerts exist)
# ===========================================================================

# Merge new backend alerts into session state
for alert in alerts_list:
    a_type = alert.get("type", "")
    if a_type and a_type not in st.session_state.resolved_types:
        st.session_state.active_alerts[a_type] = alert

# SOS banner — tier 3
sos_alerts = [a for a in st.session_state.active_alerts.values() if a.get("tier") == 3]
if sos_alerts:
    st.markdown("""
    <div style="background:#7f1d1d; border:2px solid #ef4444; border-radius:8px;
                padding:16px 20px; margin-bottom:16px; animation:pulse 1s infinite;">
        <h3 style="color:#fca5a5; margin:0;">🚨 SOS — IMMEDIATE HUMAN INTERVENTION REQUIRED</h3>
    </div>
    <style>@keyframes pulse{0%,100%{border-color:#ef4444;}50%{border-color:#fca5a5;}}</style>
    """, unsafe_allow_html=True)

# Tier 3 → Tier 2 → Tier 1 alert cards
for tier_level, tier_label, tier_color in [
    (3, "Tier 3 — SOS", "#ef4444"),
    (2, "Tier 2 — Awaiting Human Review", "#f59e0b"),
    (1, "Tier 1 — Auto-resolved", "#22c55e"),
]:
    tier_alerts = [
        a for a in st.session_state.active_alerts.values()
        if a.get("tier") == tier_level
        and a.get("type") not in st.session_state.resolved_types
    ]
    if not tier_alerts:
        continue

    st.markdown(f"### {tier_label}")

    for alert in tier_alerts:
        a_type = alert.get("type", "unknown")
        z      = alert.get("z_score", 0.0)
        val    = alert.get("current_value", 0.0)
        b_m    = alert.get("baseline_mean", 0.0)
        msg    = alert.get("message", "")
        junc   = alert.get("junction", "")

        with st.container():
            st.markdown(
                f'<div style="border-left:4px solid {tier_color}; '
                f'padding:8px 16px; margin-bottom:8px; '
                f'background:rgba(255,255,255,0.03); border-radius:4px;">'
                f'<b style="color:{tier_color};">{METRIC_LABELS.get(a_type, a_type)}'
                f'{"  [" + junc + "]" if junc else ""}</b><br>'
                f'<small style="color:#94a3b8;">{msg}</small></div>',
                unsafe_allow_html=True
            )

            action_cols = st.columns(4)
            btn_key = f"{a_type}_{tier_level}"

            with action_cols[0]:
                if st.button("✅ Acknowledge", key=f"ack_{btn_key}"):
                    resolve_alert(a_type, "ACKNOWLEDGED", "Operator acknowledged.")
                    st.rerun()
            with action_cols[1]:
                if st.button("🔍 False Positive", key=f"fp_{btn_key}"):
                    resolve_alert(a_type, "FALSE_POSITIVE", "Marked as false positive.")
                    st.rerun()
            with action_cols[2]:
                if st.button("📤 Escalate MLOps", key=f"esc_{btn_key}"):
                    resolve_alert(a_type, "ESCALATED", "Escalated to MLOps.")
                    st.rerun()
            if tier_level == 3:
                with action_cols[3]:
                    if st.button("🛑 Override AI", key=f"ovr_{btn_key}"):
                        resolve_alert(a_type, "OVERRIDDEN", "Manual override activated.")
                        st.rerun()
            elif tier_level == 2:
                with action_cols[3]:
                    with st.expander("✏️ Add notes & resolve"):
                        notes_input = st.text_area("Operator notes", key=f"notes_{btn_key}")
                        if st.button("Submit resolution", key=f"sub_{btn_key}"):
                            resolve_alert(a_type, "RESOLVED", notes_input)
                            st.rerun()

st.markdown("---")

# ===========================================================================
# SECTION 2 — DRIFT INDICATORS (9 metrics)
# ===========================================================================

st.header("📊 Drift Indicators (9 Factors)")

# Threshold mode badge
if mode == "active":
    st.markdown(
        '<span style="background:#166534; color:#86efac; padding:4px 12px; '
        'border-radius:20px; font-size:13px;">Dynamic thresholds — Z-score based</span>',
        unsafe_allow_html=True
    )
elif learning:
    st.markdown(
        f'<span style="background:#713f12; color:#fde68a; padding:4px 12px; '
        f'border-radius:20px; font-size:13px;">Static thresholds — building baseline '
        f'({run_count}/30 runs)</span>',
        unsafe_allow_html=True
    )

st.markdown("<br>", unsafe_allow_html=True)

if not metrics:
    st.info("Waiting for metric data from the backend...")
else:
    row1 = st.columns(3)
    row2 = st.columns(3)
    row3 = st.columns(3)
    col_groups = [row1, row2, row3]

    for i, key in enumerate(METRIC_KEYS):
        row_idx = i // 3
        col_idx = i % 3
        col = col_groups[row_idx][col_idx]

        with col:
            val   = metrics.get(key, 0.0)
            z     = z_scores.get(key)
            mean  = b_mean.get(key)
            qual  = baseline_quality.get(key, {})
            stable = qual.get("is_stable", True) if isinstance(qual, dict) else True

            label = METRIC_LABELS.get(key, key)
            fmt = ".0f" if key in ("technology_influence", "event_traffic") else ".4f"

            render_metric_card(
                label=label, key=key, value=val,
                z_score=z, mean=mean,
                is_stable=stable, learning=learning,
                fmt=fmt
            )

st.markdown("---")

# ===========================================================================
# SECTION 3 — BASELINE vs CURRENT COMPARISON
# ===========================================================================

if mode == "active" and metrics and b_mean:
    st.header("📈 Baseline vs Current Comparison")

    comparison_data = []
    for key in METRIC_KEYS:
        current = metrics.get(key)
        baseline = b_mean.get(key)
        z = z_scores.get(key)
        if current is None or baseline is None:
            continue
        comparison_data.append({
            "Metric": METRIC_LABELS.get(key, key),
            "Baseline mean": round(baseline, 4),
            "Current value": round(current, 4),
            "Z-score": round(z, 2) if z is not None else None,
            "Status": (
                "🔴 Critical" if z and abs(z) >= 3.0 else
                "🟠 Anomaly"  if z and abs(z) >= 2.3 else
                "🟡 Elevated" if z and abs(z) >= 2.0 else
                "🟢 Normal"
            )
        })

    if comparison_data:
        cdf = pd.DataFrame(comparison_data)
        st.dataframe(cdf, use_container_width=True, hide_index=True)

        # Visual comparison bar chart
        fig = go.Figure()
        labels = [d["Metric"] for d in comparison_data]
        baselines = [d["Baseline mean"] for d in comparison_data]
        currents  = [d["Current value"] for d in comparison_data]

        fig.add_trace(go.Bar(
            name="Baseline mean",
            x=labels, y=baselines,
            marker_color="#3b82f6", opacity=0.7
        ))
        fig.add_trace(go.Bar(
            name="Current value",
            x=labels, y=currents,
            marker_color="#f59e0b", opacity=0.9
        ))
        fig.update_layout(
            barmode="group",
            title="Baseline vs Current — all 9 metrics",
            template="plotly_dark",
            height=400,
            xaxis_tickangle=-30,
            legend=dict(orientation="h", y=1.1)
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

# ===========================================================================
# SECTION 4 — GEMINI AI EXPLANATION
# ===========================================================================

st.header("🧠 AI Explanation")

explanation_data = safe_get("/explanation")
if explanation_data:
    exp = explanation_data.get("explanation", {})
    if isinstance(exp, str):
        st.write(exp)
    elif isinstance(exp, dict):
        col_exp1, col_exp2 = st.columns(2)
        with col_exp1:
            cause = exp.get("cause") or exp.get("root_cause", "")
            if cause:
                st.markdown(
                    f'<div style="background:#14532d; border-radius:8px; padding:14px;">'
                    f'<b style="color:#86efac;">Root Cause:</b><br>'
                    f'<span style="color:#dcfce7;">{cause}</span></div>',
                    unsafe_allow_html=True
                )
            reasons = exp.get("reasons", [])
            if reasons:
                st.markdown("**Reasons:**")
                for r in reasons:
                    st.markdown(f"- {r}")
        with col_exp2:
            actions = exp.get("recommended_actions", exp.get("actions", []))
            if actions:
                st.markdown(
                    '<div style="background:#1e3a5f; border-radius:8px; padding:14px;">'
                    '<b style="color:#93c5fd;">Recommended Actions:</b></div>',
                    unsafe_allow_html=True
                )
                for i, a in enumerate(actions, 1):
                    st.markdown(f"{i}. {a}")
    else:
        st.info("No AI explanation available. Ensure the /explanation endpoint is running.")
else:
    # Graceful fallback when no active alerts
    active_count = len(st.session_state.active_alerts)
    if active_count == 0:
        st.success("✅ System Operating Normally — All Alerts Resolved")
        col_e1, col_e2 = st.columns(2)
        with col_e1:
            st.markdown(
                '<div style="background:#14532d; border-radius:8px; padding:14px;">'
                '<b style="color:#86efac;">Root Cause:</b><br>'
                '<span style="color:#dcfce7;">System operating within expected parameters. '
                'Recent decisions align with baseline historical data.</span></div>',
                unsafe_allow_html=True
            )
            st.markdown("**Reasons:**")
            st.markdown("- All drift metrics are within expected thresholds.")
            st.markdown("- No anomalous behaviour detected.")
        with col_e2:
            st.markdown(
                '<div style="background:#1e3a5f; border-radius:8px; padding:14px;">'
                '<b style="color:#93c5fd;">Recommended Operations Action:</b></div>',
                unsafe_allow_html=True
            )
            st.markdown("1. Continue standard monitoring. No intervention required.")
    else:
        st.warning("AI explanation endpoint unreachable. Check `/explanation` route on your backend.")

st.markdown("---")

# ===========================================================================
# SECTION 5 — HUMAN-IN-THE-LOOP ALERT MANAGEMENT
# ===========================================================================

st.header("📋 Human-in-the-Loop Alert Management")

hitl_data = safe_get("/alerts")
if hitl_data:
    pending_alerts = hitl_data.get("alerts", [])
    for alert in pending_alerts:
        a_type = alert.get("alert_type", "")
        if not a_type or a_type in st.session_state.resolved_types:
            continue

        severity = SEVERITY_MAP.get(a_type, "Medium")
        sev_color = SEVERITY_COLORS.get(severity, "#94a3b8")

        with st.expander(
            f"Manage Alert: {alert.get('alert_text', a_type)}", expanded=True
        ):
            st.markdown(
                f"**Alert Type:** "
                f'<span style="color:{sev_color};">{a_type}</span> | '
                f"**Severity:** "
                f'<span style="color:{sev_color};">{severity}</span>',
                unsafe_allow_html=True
            )
            desc = alert.get("alert_text", "")
            if desc:
                st.markdown(f"**Description:** {desc}")
            created = alert.get("created_at", "")
            if created:
                st.markdown(
                    f'**Created Time:** '
                    f'<span style="color:#f59e0b;">{created[:19]}</span>',
                    unsafe_allow_html=True
                )

            op_notes = st.text_area(
                "Operator Notes", key=f"hitl_notes_{a_type}",
                placeholder="Enter resolution notes here..."
            )

            hitl_cols = st.columns(4)
            with hitl_cols[0]:
                if st.checkbox("Acknowledge Alert", key=f"hitl_ack_{a_type}"):
                    resolve_alert(a_type, "ACKNOWLEDGED", op_notes)
                    st.rerun()
            with hitl_cols[1]:
                if st.checkbox("Mark Resolved",    key=f"hitl_res_{a_type}"):
                    resolve_alert(a_type, "RESOLVED", op_notes)
                    st.rerun()

if not hitl_data or not hitl_data.get("alerts"):
    st.info("No active alerts awaiting human review.")

st.markdown("---")

# ===========================================================================
# SECTION 6 — WHAT-IF SIMULATION
# ===========================================================================

st.header("🧪 Drift Injection / What-If Simulation")
st.caption("Adjust parameters to observe how Sentinel responds in real time")

sim_col1, sim_col2 = st.columns(2)
with sim_col1:
    sim_traffic = st.slider("Traffic Volume", 100, 600, 298, step=10)
    sim_accident = st.toggle("Accident Active", value=False)
with sim_col2:
    sim_lanes = st.slider("Active Lanes", 1, 6, 3, step=1)
    sim_event  = st.toggle("Event Traffic Surge", value=False)

if st.button("🚀 Run Simulation", type="primary", use_container_width=True):
    sim_response = safe_post("/simulate-drift", {
        "traffic_volume":       sim_traffic,
        "active_lanes":         sim_lanes,
        "accident_active":      sim_accident,
        "event_traffic_active": sim_event,
    })
    st.session_state.sim_results = sim_response

if st.session_state.sim_results:
    sr = st.session_state.sim_results
    newly  = sr.get("newly_triggered", [])
    resolved_by_sim = sr.get("resolved_by_simulation", [])

    if newly:
        st.error(
            f"🚨 Simulation triggered {len(newly)} new drift alert(s): "
            + ", ".join(newly)
        )
    elif resolved_by_sim:
        st.info(
            f"🔧 Simulation resolved {len(resolved_by_sim)} alert(s): "
            + ", ".join(resolved_by_sim)
        )
    else:
        st.success("✅ No new drift detected under these conditions. System is stable.")

    # Side-by-side comparison
    b_sim = sr.get("baseline_metrics", {})
    s_sim = sr.get("simulated_metrics", {})

    if b_sim or s_sim:
        st.subheader("Baseline vs Simulated — comparison")
        sim_cmp_col1, sim_cmp_col2 = st.columns(2)

        b_alerts_set = {a.get("type") for a in sr.get("baseline_alerts", [])}
        s_alerts_set = {a.get("type") for a in sr.get("simulated_alerts", [])}

        with sim_cmp_col1:
            st.markdown("**📊 Baseline (last 500 real decisions)**")
            for k in METRIC_KEYS:
                bv = b_sim.get(k)
                if bv is None:
                    continue
                badge = "🔴 ALERT" if k in b_alerts_set else "🟢 OK"
                st.markdown(
                    f"**{METRIC_LABELS.get(k, k)}:** `{bv:.4f}` {badge}"
                )

        with sim_cmp_col2:
            st.markdown("**🧪 Simulated (with your parameters)**")
            for k in METRIC_KEYS:
                sv = s_sim.get(k)
                if sv is None:
                    continue
                bv = b_sim.get(k, sv)
                changed = abs(sv - bv) > 0.001
                if k in newly:
                    badge = "🔴 NEW ALERT"
                    color = "#ef4444"
                elif k in s_alerts_set:
                    badge = "🔴 ALERT"
                    color = "#f97316"
                elif changed:
                    badge = "🟡 CHANGED"
                    color = "#f59e0b"
                else:
                    badge = "🟢 OK"
                    color = "#22c55e"
                st.markdown(
                    f'**{METRIC_LABELS.get(k, k)}:** '
                    f'`{sv:.4f}` '
                    f'<span style="color:{color};">{badge}</span>',
                    unsafe_allow_html=True
                )

        # What changed in plain English
        if newly or resolved_by_sim:
            st.subheader("💬 What changed (plain English)")
            for i, k in enumerate(METRIC_KEYS, 1):
                sv = s_sim.get(k)
                if sv is None:
                    continue
                translation = get_translation(k, sv)
                label = METRIC_LABELS.get(k, k)
                st.markdown(f"**{i}. {label}:** {translation}")

st.markdown("---")

# ===========================================================================
# SECTION 7 — CONTEXTUAL ANALYTICS CHARTS
# ===========================================================================

if logs:
    st.subheader("📉 Contextual Analytics")
    df_logs = pd.DataFrame(logs)
    df_logs["timestamp"] = pd.to_datetime(
        df_logs.get("timestamp", df_logs.get("event_time", pd.Series(dtype=str))),
        errors="coerce"
    )

    if "traffic_volume" in df_logs.columns:
        df_logs["traffic"] = df_logs["traffic_volume"]
    elif "traffic" not in df_logs.columns:
        df_logs["traffic"] = 100

    if "active_lanes" not in df_logs.columns:
        df_logs["active_lanes"] = df_logs["traffic"].apply(
            lambda x: 3 if x > 200 else (2 if x > 100 else 1)
        )

    if "congestion_level" not in df_logs.columns:
        df_logs["congestion_level"] = df_logs["traffic"] / (df_logs["active_lanes"] * 120)

    if "reason" not in df_logs.columns:
        df_logs["reason"] = df_logs.apply(
            lambda row: (
                "Simulated accident" if row.get("has_incident")
                else "Peak hour rush" if row.get("is_peak_hour")
                else "Normal flow"
            ),
            axis=1
        )

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        fig_scatter = px.scatter(
            df_logs, x="traffic", y="active_lanes", color="congestion_level",
            title="AI Decision Mapping (Traffic vs Lanes)", template="plotly_dark"
        )
        st.plotly_chart(fig_scatter, use_container_width=True)

    with chart_col2:
        event_counts = df_logs["reason"].value_counts().reset_index()
        event_counts.columns = ["Reason", "Count"]
        fig_pie = px.pie(
            event_counts, values="Count", names="Reason",
            title="Event Distribution Triggering AI Behaviour",
            template="plotly_dark"
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    st.markdown("---")

# ===========================================================================
# SECTION 8 — AUDIT LOG
# ===========================================================================

st.header("📜 Audit Log")

audit_data = safe_get("/audit")
audit_rows = []
if audit_data:
    audit_rows = audit_data.get("audit_log", [])

if not audit_rows:
    st.info("No audit records found yet. Resolved alerts will appear here.")
else:
    # Filters
    f1, f2, f3 = st.columns([1, 1, 2])
    all_types = sorted({r.get("alert_type", "—") or "—" for r in audit_rows})

    with f1:
        sev_filter = st.selectbox("Filter by Severity", ["All", "High", "Medium", "Low"])
    with f2:
        type_filter = st.selectbox("Filter by Alert Type", ["All"] + all_types)
    with f3:
        date_range = st.date_input("Date range", value=[])

    filtered = audit_rows
    if sev_filter != "All":
        filtered = [
            r for r in filtered
            if SEVERITY_MAP.get(r.get("alert_type", ""), "Medium") == sev_filter
        ]
    if type_filter != "All":
        filtered = [r for r in filtered if (r.get("alert_type") or "—") == type_filter]
    if date_range and len(date_range) == 2:
        start_d, end_d = date_range
        filtered = [
            r for r in filtered
            if r.get("resolved_at") and
            start_d <= datetime.datetime.fromisoformat(r["resolved_at"][:10]).date() <= end_d
        ]

    # Pagination
    PAGE_SIZE = 10
    total_pages = max(1, (len(filtered) + PAGE_SIZE - 1) // PAGE_SIZE)
    if st.session_state.audit_page >= total_pages:
        st.session_state.audit_page = total_pages - 1

    start_idx = st.session_state.audit_page * PAGE_SIZE
    page_rows = filtered[start_idx: start_idx + PAGE_SIZE]

    # Styled HTML table
    def build_badge(severity: str) -> str:
        color = SEVERITY_COLORS.get(severity, "#94a3b8")
        return (
            f'<span style="background:{color}; color:white; padding:2px 8px; '
            f'border-radius:9999px; font-size:11px; font-weight:600;">{severity}</span>'
        )

    def build_check(val: bool) -> str:
        return "✅" if val else '<span style="color:#94a3b8;">—</span>'

    table_html = """
    <style>
    .audit-table{width:100%;border-collapse:collapse;font-family:'Inter',sans-serif;font-size:13px;}
    .audit-table th{background:#1e293b;color:#e2e8f0;padding:10px 8px;text-align:left;border-bottom:2px solid #334155;}
    .audit-table td{padding:8px;border-bottom:1px solid #334155;color:#cbd5e1;}
    .audit-table tr:hover td{background:#1e293b;}
    </style>
    <table class="audit-table">
    <thead><tr>
    <th>Alert ID</th><th>Alert Type</th><th>Severity</th><th>Description</th>
    <th>Created At</th><th>Ack</th><th>Resolved</th><th>Operator Notes</th><th>Action Taken</th>
    </tr></thead><tbody>
    """
    for row in page_rows:
        a_type   = row.get("alert_type") or "—"
        severity = SEVERITY_MAP.get(a_type, "Medium")
        r_status = row.get("status", "")
        is_ack   = r_status in ("ACKNOWLEDGED", "RESOLVED")
        is_res   = r_status == "RESOLVED"
        table_html += (
            f"<tr>"
            f"<td><code>{str(row.get('id',''))[:8]}</code></td>"
            f"<td>{a_type}</td>"
            f"<td>{build_badge(severity)}</td>"
            f"<td>{(row.get('alert_text') or '—')[:60]}</td>"
            f"<td>{(row.get('resolved_at') or '—')[:19]}</td>"
            f"<td style='text-align:center;'>{build_check(is_ack)}</td>"
            f"<td style='text-align:center;'>{build_check(is_res)}</td>"
            f"<td>{row.get('operator_notes') or ''}</td>"
            f"<td>{_derive_action(r_status)}</td>"
            f"</tr>"
        )
    table_html += "</tbody></table>"
    st.markdown(table_html, unsafe_allow_html=True)

    # Pagination controls
    pc1, pc2, pc3 = st.columns([1, 2, 1])
    with pc1:
        if st.button("← Previous", disabled=(st.session_state.audit_page == 0)):
            st.session_state.audit_page -= 1
            st.rerun()
    with pc2:
        st.markdown(
            f"<p style='text-align:center; color:#94a3b8;'>Page "
            f"{st.session_state.audit_page + 1} of {total_pages} "
            f"({len(filtered)} records)</p>",
            unsafe_allow_html=True
        )
    with pc3:
        if st.button("Next →", disabled=(st.session_state.audit_page >= total_pages - 1)):
            st.session_state.audit_page += 1
            st.rerun()

    # PDF Export
    st.markdown("<br>", unsafe_allow_html=True)
    pdf_bytes = generate_audit_pdf(filtered, metrics)
    st.download_button(
        label="📄 Export PDF Report",
        data=pdf_bytes,
        file_name=f"sentinel_audit_report_{datetime.datetime.now().strftime('%Y-%m-%d')}.pdf",
        mime="application/pdf",
        type="primary",
    )