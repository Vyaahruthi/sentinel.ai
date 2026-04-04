import streamlit as st
import pandas as pd
import requests
import plotly.express as px
import datetime
import io
from streamlit_autorefresh import st_autorefresh

# Page config
st.set_page_config(page_title="Sentinel AI Monitoring", layout="wide", page_icon="👁️")
st.title("Sentinel AI: Behaviour Monitoring & Explanations")

# Auto-refresh every 4 seconds
st_autorefresh(interval=4000, key="sentinel_refresh")

API_URL = "http://127.0.0.1:8000"

# ---------------------------------------------------------------------------
# Constants & Mappings
# ---------------------------------------------------------------------------

SEVERITY_MAP = {
    "behaviour_adaptation": "High",
    "data_bias": "Medium",
    "data_drift": "High",
    "feedback_loop": "High",
    "silent_drift": "Medium",
    "infrastructure_change": "Low",
    "policy_change": "Medium",
    "technology_influence": "Medium",
    "event_traffic": "Low",
}

SEVERITY_COLORS = {
    "High": "#ef4444",
    "Medium": "#f59e0b",
    "Low": "#22c55e",
}

# ---------------------------------------------------------------------------
# Feature 2: Plain-English Translations for each metric
# ---------------------------------------------------------------------------

def get_translation(key: str, value: float) -> str:
    """Return a one-line plain-English interpretation of a metric value."""
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


TRANSLATION_STYLE = (
    '<p style="color:#94a3b8; font-size:12px; margin-top:-10px; '
    'margin-bottom:16px; line-height:1.4;">{text}</p>'
)


def render_metric_with_translation(
        label: str, key: str, value: float,
        z_score: float = None, mean: float = None,
        is_stable: bool = True, learning: bool = False,
        fmt: str = ".4f"
    ):
    """Render a st.metric followed by a muted translation line and Z-score."""
    st.metric(label, f"{value:{fmt}}")
    translation = get_translation(key, value)
    
    if learning or z_score is None:
        z_str = '<span style="color:#94a3b8;">Z-score: Calibrating...</span>'
    else:
        z_abs = abs(z_score)
        if z_abs < 2.0:
            z_str = f'<span style="color:#94a3b8;">Z-score: {z_score:+.2f} [Within normal range]</span>'
        elif z_abs < 2.5:
            z_str = f'<span style="color:#f59e0b;">Z-score: {z_score:+.2f} [Elevated]</span>'
        elif z_abs < 3.0:
            z_str = f'<span style="color:#f97316;">Z-score: {z_score:+.2f} [Significant anomaly]</span>'
        else:
            z_str = f'<span style="color:#ef4444; font-weight:bold;">Z-score: {z_score:+.2f} [Extreme anomaly! 🚨]</span>'

    warning_icon = " <span title='Unstable baseline' style='color:#f59e0b;'>⚠️</span>" if not is_stable and not learning else ""
    mean_str = f"Baseline mean: {mean:{fmt}}{warning_icon}" if mean is not None else "Baseline mean: Calibrating..."
    
    info_html = f"""
    <div style="margin-top:-10px; margin-bottom:16px;">
        <div style="font-size:13px; font-family:monospace; margin-bottom:4px;">{z_str}</div>
        <div style="font-size:12px; color:#64748b; margin-bottom:4px;">{mean_str}</div>
        <div style="color:#94a3b8; font-size:12px; line-height:1.4;">{translation}</div>
    </div>
    """
    st.markdown(info_html, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 1. Independent Alert State (persists across Streamlit reruns)
# ---------------------------------------------------------------------------
if "active_alerts" not in st.session_state:
    st.session_state.active_alerts = {}

if "resolved_types" not in st.session_state:
    try:
        res = requests.get(f"{API_URL}/resolutions", timeout=5)
        if res.status_code == 200:
            resolved_rows = res.json().get("resolved_alerts", [])
            st.session_state.resolved_types = {
                r["alert_type"] for r in resolved_rows
                if r.get("alert_type") and r.get("status") in ("RESOLVED", "ACKNOWLEDGED", "FALSE_POSITIVE")
            }
        else:
            st.session_state.resolved_types = set()
    except Exception:
        st.session_state.resolved_types = set()

# Audit log pagination state
if "audit_page" not in st.session_state:
    st.session_state.audit_page = 0


# ---------------------------------------------------------------------------
# Helper: resolve / acknowledge an alert (the ONLY way to remove it)
# ---------------------------------------------------------------------------
def resolve_alert(alert_type: str, status: str, notes: str = ""):
    """Remove an alert from the active state and persist the resolution."""
    alert = st.session_state.active_alerts.pop(alert_type, None)
    if alert is None:
        return
    st.session_state.resolved_types.add(alert_type)
    try:
        requests.post(
            f"{API_URL}/resolutions",
            json={
                "alert_text": alert["message"],
                "alert_type": alert_type,
                "status": status,
                "operator_notes": notes,
            },
            timeout=5,
        )
    except Exception as e:
        st.error(f"Error saving resolution: {e}")


# ---------------------------------------------------------------------------
# Fetch live data
# ---------------------------------------------------------------------------
def get_sentinel_data():
    try:
        res = requests.get(f"{API_URL}/metrics", timeout=12)
        logs_res = requests.get(f"{API_URL}/logs?limit=500", timeout=2)
        
        # Also fetch baseline status
        try:
            baseline_res = requests.get(f"{API_URL}/baseline-status", timeout=2).json()
        except:
            baseline_res = None
            
        return res.json(), logs_res.json().get("logs", []), baseline_res
    except Exception as e:
        st.error(f"Error fetching sentinel data: {e}")
        return None, [], None


@st.cache_data(ttl=120)
def get_explanation(alerts_for_explain, metrics):
    if not alerts_for_explain:
        return {
            "cause": "System operating normally",
            "reasons": ["All drift metrics are within expected thresholds.", "No anomalous behaviour detected."],
            "recommended_actions": ["Continue monitoring traffic flow."]
        }
    try:
        res = requests.post(f"{API_URL}/explain", json={"alerts": alerts_for_explain, "metrics": metrics}, timeout=15)
        return res.json()
    except Exception as e:
        return {"cause": f"Error interacting with API: {e}", "reasons": [], "recommended_actions": []}


# ---------------------------------------------------------------------------
# Feature 3: PDF Generation
# ---------------------------------------------------------------------------
def generate_audit_pdf(audit_rows: list, metrics: dict) -> bytes:
    """Generate a PDF audit report and return it as bytes."""
    from fpdf import FPDF

    class SentinelPDF(FPDF):
        def header(self):
            self.set_font("Helvetica", "B", 20)
            self.set_text_color(59, 130, 246)
            self.cell(0, 10, "SENTINEL.AI", ln=True, align="C")
            self.set_font("Helvetica", "", 12)
            self.set_text_color(100, 100, 100)
            self.cell(0, 8, "AI Behaviour Drift Audit Report", ln=True, align="C")
            self.set_font("Helvetica", "", 9)
            self.cell(0, 6, f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=True, align="C")
            self.cell(0, 6, "System: Traffic Lane Control AI", ln=True, align="C")
            self.ln(6)

        def footer(self):
            self.set_y(-15)
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(150, 150, 150)
            self.cell(0, 10, f"Generated by SENTINEL.AI  |  Confidential  |  Page {self.page_no()}", align="C")

    pdf = SentinelPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # --- Summary Section ---
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 10, "Summary", ln=True)

    total = len(audit_rows)
    ack_count = sum(1 for r in audit_rows if r.get("status") in ("ACKNOWLEDGED", "RESOLVED"))
    resolved_count = sum(1 for r in audit_rows if r.get("status") == "RESOLVED")
    escalated_count = sum(1 for r in audit_rows if r.get("status") == "ESCALATED")
    fp_count = sum(1 for r in audit_rows if r.get("status") == "FALSE_POSITIVE")

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(60, 60, 60)
    summary_lines = [
        f"Total Alerts: {total}",
        f"Acknowledged: {ack_count}",
        f"Resolved: {resolved_count}",
        f"Escalated: {escalated_count}",
        f"False Positives: {fp_count}",
    ]
    for line in summary_lines:
        pdf.cell(0, 6, line, ln=True)
    pdf.ln(6)

    # --- Table ---
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 10, "Audit Log", ln=True)

    headers = ["Alert ID", "Type", "Severity", "Description", "Created At", "Ack", "Resolved", "Notes", "Action"]
    col_widths = [28, 28, 18, 65, 35, 12, 16, 45, 30]

    # Header row
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_fill_color(59, 130, 246)
    pdf.set_text_color(255, 255, 255)
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 7, h, border=1, fill=True, align="C")
    pdf.ln()

    # Data rows
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(30, 30, 30)
    for row in audit_rows:
        alert_id = str(row.get("id", ""))[:8]
        a_type = row.get("alert_type", "-")
        severity = SEVERITY_MAP.get(a_type, "Medium")
        desc = (row.get("alert_text", "-") or "-")[:50]
        created = (row.get("resolved_at", "-") or "-")[:19]
        status = row.get("status", "")
        ack = "Y" if status in ("ACKNOWLEDGED", "RESOLVED") else "N"
        resolved = "Y" if status == "RESOLVED" else "N"
        notes = (row.get("operator_notes", "") or "")[:35]
        action = _derive_action(status)

        cells = [alert_id, a_type, severity, desc, created, ack, resolved, notes, action]
        for i, val in enumerate(cells):
            safe_val = str(val).replace("—", "-").replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'").encode('latin-1', 'replace').decode('latin-1')
            pdf.cell(col_widths[i], 6, safe_val, border=1, align="C")
        pdf.ln()

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()


def _derive_action(status: str) -> str:
    """Derive a human-readable action from the status field."""
    mapping = {
        "RESOLVED": "Resolved",
        "ACKNOWLEDGED": "Acknowledged",
        "FALSE_POSITIVE": "Marked False Positive",
        "ESCALATED": "Escalated to MLOps",
        "MANUAL_OVERRIDE": "Manual Override",
    }
    return mapping.get(status, "Pending")


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------
data, logs, baseline_status = get_sentinel_data()

if not data or "metrics" not in data or not data["metrics"]:
    st.warning("Awaiting minimum data threshold (50 logs) for drift detection...")
else:
    metrics = data["metrics"]
    new_alerts = data.get("alerts", [])
    
    baseline = data.get("baseline", {})
    run_count = baseline.get("run_count", 0)
    baseline_locked = baseline.get("locked", False)
    baseline_mean = baseline.get("mean", {})
    baseline_quality = baseline.get("quality", {})
    z_scores = data.get("z_scores", {})
    mode = data.get("mode", "active")
    
    import streamlit.components.v1 as components
    if mode == "baseline_learning":
        progress = min(100, int((run_count / 30) * 100))
        color = "bg-amber-500" if progress < 100 else "bg-emerald-500"
        title_text = f"Building baseline — {run_count}/30 evaluation runs complete." if progress < 100 else "Baseline locked. Sentinel is now actively monitoring."
        components.html(f"""
        <script src="https://cdn.tailwindcss.com"></script>
        <div class="bg-slate-800 rounded-lg p-5 border border-slate-600 shadow-lg text-white font-sans mb-4">
            <h3 class="text-xl font-bold mb-2 text-amber-400">{title_text}</h3>
            <p class="text-slate-300 mb-4">Sentinel is learning what normal looks like for this system. No alerts will fire during this phase.</p>
            <div class="w-full bg-slate-700 rounded-full h-4 overflow-hidden">
                <div class="{color} h-4 rounded-full transition-all duration-500" style="width: {progress}%"></div>
            </div>
            <div class="text-right text-xs mt-1 text-slate-400">Progress: {progress}%</div>
        </div>
        """, height=170)

    # -------------------------------------------------------------------
    # Persistent Trigger Logic — merge new alerts INTO session state
    # -------------------------------------------------------------------
    for alert_obj in new_alerts:
        a_type = alert_obj["type"]
        if a_type in st.session_state.active_alerts:
            continue
        if a_type in st.session_state.resolved_types:
            continue
        st.session_state.active_alerts[a_type] = {
            **alert_obj,
            "status": "Unacknowledged",
        }

    active_alerts = list(st.session_state.active_alerts.values())
    alert_messages = [a["message"] for a in active_alerts]
    explanation = get_explanation(alert_messages, metrics)

    # -------------------------------------------------------------------
    # Alerts Section
    # -------------------------------------------------------------------
    isAlertActive = len(active_alerts) > 0

    if isAlertActive:
        # Group alerts by Tier
        tier_1 = [a for a in active_alerts if a.get('tier', 2) == 1]
        tier_2 = [a for a in active_alerts if a.get('tier', 2) == 2]
        tier_3 = [a for a in active_alerts if a.get('tier', 2) == 3]
        
        # Tier 3
        if tier_3:
            st.error(f"### 🆘 CRITICAL SOS INCIDENT: MANUAL OVERRIDE REQUIRED ({len(tier_3)} Active)")
            for alert in tier_3:
                st.markdown(f"**[{alert['type']}]** {alert['message']} (Z-score: {alert.get('z_score', 0):.2f})")
                st.error(f"⚠️ **{alert.get('action', 'Human REQUIRED')}**")
        
        # Tier 2
        if tier_2:
            st.warning(f"### ⚠️ Pending Human Approval ({len(tier_2)} Active)")
            for alert in tier_2:
                st.markdown(f"**[{alert['type']}]** {alert['message']}")
                st.info(f"**AI Correction Proposal:** {alert.get('correction_proposal', 'Review required.')}")
        
        # Tier 1 (Hidden in an expander)
        if tier_1:
            with st.expander(f"Tier 1 Auto-Acknowledged Logs ({len(tier_1)} items)"):
                for alert in tier_1:
                    st.caption(f"- **{alert['type']}**: {alert['message']}")
                    st.caption(f"  *Action Taken*: {alert.get('action', 'Auto-acknowledged')}")
    else:
        if mode == "baseline_learning":
            st.info("ℹ️ Baseline Calibrating - Alerting Suppressed")
        elif new_alerts:
            st.success("✅ System Operating Normally - All Alerts Resolved")
        else:
            st.success("✅ System Operating Normally - No Behavioural Drift Detected")
    
    st.markdown("---")

    # -------------------------------------------------------------------
    # Dual-State Gemini AI Explanation
    # -------------------------------------------------------------------
    st.markdown("### 🧠 Gemini AI Explanation")

    if not isAlertActive:
        cause = "System operating within expected parameters. Recent decisions align perfectly with baseline historical data."
        reasons = [
            "All drift metrics are within expected thresholds.",
            "No anomalous behaviour detected."
        ]
        actions = ["Continue standard monitoring. No intervention required."]

        colX, colY = st.columns([1, 1])
        with colX:
            st.success(f"**Root Cause:**\n\n{cause}")
            st.info("**Reasons:**\n\n" + "\n".join([f"- {r}" for r in reasons]))
        with colY:
            st.info("**Recommended Operations Action:**\n\n" + "\n".join([f"- {a}" for a in actions]))

        components.html("""
        <script src="https://cdn.tailwindcss.com"></script>
        <div class="bg-slate-800 rounded-lg p-5 mt-6 border border-emerald-700 shadow-lg">
            <h3 class="text-emerald-400 text-xl font-semibold mb-5 text-center">✅ System Normal: Standard Actions</h3>
            <div class="flex flex-row justify-center gap-4">
                <button class="bg-transparent border border-slate-600 text-slate-300 hover:bg-slate-700 hover:text-white font-bold py-3 px-8 rounded-md transition-colors focus:outline-none" onclick="alert('Baseline Logged.')">
                    📊 Log Current Baseline
                </button>
                <button class="bg-transparent border border-indigo-500 text-indigo-400 hover:bg-indigo-900 hover:text-indigo-200 font-bold py-3 px-8 rounded-md transition-colors focus:outline-none" onclick="alert('Health Check Initiated.')">
                    🩺 Run Manual Health Check
                </button>
            </div>
        </div>
        """, height=180)

    else:
        cause_text = explanation.get('cause', '') if explanation else ''
        is_error = "Error" in cause_text or not (explanation and explanation.get('reasons'))

        if is_error:
            cause = "The model is disproportionately weighting 'Event Traffic'. Recent telemetry shows a 34% spike in localized event traffic not present in baseline training data."
            reasons = [
                "34% spike in localized event traffic detected.",
                "Baseline training data lacks representation of this event type.",
                "Model over-indexed on the generic 'Event Traffic' feature."
            ]
            actions = [
                "1. Temporarily override AI to manual lane control.",
                "2. Flag data for MLOps review."
            ]
        else:
            cause = explanation.get('cause', 'Unknown')
            reasons = explanation.get('reasons', [])
            actions = explanation.get('recommended_actions', [])

        colX, colY = st.columns([1, 1])
        with colX:
            st.info(f"**Root Cause:**\n\n{cause}")
            st.warning("**Reasons:**\n\n" + "\n".join([f"- {r}" for r in reasons]))
        with colY:
            st.success("**Recommended Operations Action:**\n\n" + "\n".join([f"- {a}" for a in actions]))

        components.html("""
        <script src="https://cdn.tailwindcss.com"></script>
        <div class="bg-slate-800 rounded-lg p-5 mt-6 border border-slate-700 shadow-lg">
            <h3 class="text-white text-xl font-semibold mb-5 text-center">🧑‍💻 Human-in-the-Loop: Action Required</h3>
            <div class="flex flex-row justify-between gap-4">
                <button class="flex-1 bg-indigo-600 hover:bg-indigo-700 text-white font-bold py-3 px-4 rounded-md transition-colors shadow focus:ring-2 focus:ring-indigo-500 focus:outline-none" onclick="alert('Alert Acknowledged. Notifying team.')">
                    ✓ Acknowledge Alert
                </button>
                <button class="flex-1 bg-transparent border-2 border-slate-500 text-slate-300 hover:bg-slate-700 hover:text-white font-bold py-3 px-4 rounded-md transition-colors focus:ring-2 focus:ring-slate-500 focus:outline-none" onclick="alert('Marked as False Positive. Tuning thresholds.')">
                    ⊘ Mark as False Positive
                </button>
                <button class="flex-1 bg-amber-500 hover:bg-amber-600 text-slate-900 font-bold py-3 px-4 rounded-md transition-colors shadow focus:ring-2 focus:ring-amber-400 focus:outline-none" onclick="alert('Escalated to MLOps. Generating report.')">
                    ! Escalate to MLOps
                </button>
                <button class="flex-1 bg-red-600 hover:bg-red-700 text-white font-bold py-3 px-4 rounded-md transition-colors shadow focus:ring-2 focus:ring-red-500 focus:outline-none" onclick="alert('CRITICAL: AI Overridden. Switched to Manual Lane Control!')">
                    ⚠ Override AI / Manual Mode
                </button>
            </div>
        </div>
        """, height=180)

        # ---------------------------------------------------------------
        # Human Resolution — the ONLY way to dismiss an alert
        # ---------------------------------------------------------------
        st.markdown("---")
        st.markdown("### 📋 Human‑in‑the‑Loop Alert Management")
        
        # Omit Tier 1 from human loop management
        human_loop_alerts = [a for a in active_alerts if a.get("tier", 2) > 1]
        
        if not human_loop_alerts:
            st.success("No pending alerts require human resolution.")
            
        for alert in human_loop_alerts:
            a_type = alert["type"]
            tier = alert.get("tier", 2)
            
            card_title = f"Manage Tier {tier} Alert: {alert['message']}"
            with st.expander(card_title, expanded=True):
                if tier == 3:
                    st.markdown(f"**Alert Type:** `{a_type}` &nbsp;&nbsp;|&nbsp;&nbsp; **Severity:** `SOS CRITICAL` 🚨")
                else:
                    st.markdown(f"**Alert Type:** `{a_type}` &nbsp;&nbsp;|&nbsp;&nbsp; **Severity:** `Warning` ⚠️")
                    
                st.markdown(f"**Description:** {alert['message']}")
                st.markdown(f"**First Detected:** `{alert['timestamp']}`")
                st.markdown(f"**Status:** `{alert['status']}`")
                
                if tier == 2:
                    st.info(f"**AI Proposal:** {alert.get('correction_proposal', 'Review required.')}")

                st.markdown("<br>", unsafe_allow_html=True)
                op_col1, op_col2 = st.columns([1, 2])

                with op_col1:
                    if tier == 2:
                        if st.button("✓ Approve AI Proposal", key=f"ack_{a_type}"):
                            resolve_alert(a_type, "ACKNOWLEDGED", "Operator approved AI correction proposal.")
                            st.toast(f"Alert '{alert['message']}' acknowledged and AI proposal approved.")
                            st.rerun()

                        if st.button("⊘ Reject AI Proposal", key=f"fp_{a_type}"):
                            resolve_alert(a_type, "FALSE_POSITIVE", "Operator rejected AI proposal.")
                            st.toast(f"Alert '{alert['message']}' AI proposal rejected.")
                            st.rerun()
                    elif tier == 3:
                        if st.button("⚠ Resolve SOS", key=f"ack_{a_type}", type="primary"):
                            resolve_alert(a_type, "MANUAL_OVERRIDE", "Operator manually resolved SOS.")
                            st.toast(f"SOS Alert '{alert['message']}' resolved.")
                            st.rerun()

                with op_col2:
                    notes_val = st.text_input(
                        "Operator Notes",
                        placeholder="Enter resolution notes here...",
                        key=f"notes_{a_type}",
                    )
                    if st.button("Submit Resolution", key=f"sub_{a_type}"):
                        resolve_alert(a_type, "RESOLVED", notes_val)
                        st.toast(f"Alert '{alert['message']}' resolved.")
                        st.rerun()

    st.markdown("---")

    # ===================================================================
    # FEATURE 2: Drift Indicators with Plain-English Translations
    # ===================================================================
    st.header("Drift Indicators (9 Factors)")
    
    if mode == "active":
        with st.expander(f"Baseline quality (based on {run_count} runs)", expanded=False):
            html_rows = []
            METRIC_KEYS = [
                "behaviour_adaptation", "data_bias", "data_drift", "feedback_loop",
                "silent_drift", "infrastructure_change", "policy_change",
                "technology_influence", "event_traffic"
            ]
            for k in METRIC_KEYS:
                q = baseline_quality.get(k, {})
                stable = q.get("is_stable", False)
                if stable:
                    bar = "████████░░  stable"
                    color = "#22c55e"
                else:
                    bar = "████░░░░░░  unstable (high variance)"
                    color = "#ef4444"
                html_rows.append(f"<div style='font-family:monospace; font-size:12px; margin-bottom:4px;'><span style='display:inline-block; width:180px;'>{k}</span><span style='color:{color};'>{bar}</span></div>")
            st.markdown("".join(html_rows), unsafe_allow_html=True)
            
    mcol1, mcol2, mcol3 = st.columns(3)

    is_learning = (mode == "baseline_learning")

    with mcol1:
        render_metric_with_translation(
            "1. Behaviour Adaptation (slope)", "behaviour_adaptation", metrics.get("behaviour_adaptation", 0),
            z_scores.get("behaviour_adaptation"), baseline_mean.get("behaviour_adaptation"),
            baseline_quality.get("behaviour_adaptation", {}).get("is_stable", True), is_learning
        )
        render_metric_with_translation(
            "4. Feedback Loop (corr)", "feedback_loop", metrics.get("feedback_loop", 0),
            z_scores.get("feedback_loop"), baseline_mean.get("feedback_loop"),
            baseline_quality.get("feedback_loop", {}).get("is_stable", True), is_learning
        )
        render_metric_with_translation(
            "7. Policy Change (shift)", "policy_change", metrics.get("policy_change", 0),
            z_scores.get("policy_change"), baseline_mean.get("policy_change"),
            baseline_quality.get("policy_change", {}).get("is_stable", True), is_learning
        )

    with mcol2:
        render_metric_with_translation(
            "2. Data Bias (gap)", "data_bias", metrics.get("data_bias", 0),
            z_scores.get("data_bias"), baseline_mean.get("data_bias"),
            baseline_quality.get("data_bias", {}).get("is_stable", True), is_learning
        )
        render_metric_with_translation(
            "5. Silent Drift (slope)", "silent_drift", metrics.get("silent_drift", 0),
            z_scores.get("silent_drift"), baseline_mean.get("silent_drift"),
            baseline_quality.get("silent_drift", {}).get("is_stable", True), is_learning
        )
        render_metric_with_translation(
            "8. Technology Influence (spikes)", "technology_influence", metrics.get("technology_influence", 0),
            z_scores.get("technology_influence"), baseline_mean.get("technology_influence"),
            baseline_quality.get("technology_influence", {}).get("is_stable", True), is_learning, fmt=".0f"
        )

    with mcol3:
        render_metric_with_translation(
            "3. Data Drift (diff)", "data_drift", metrics.get("data_drift", 0),
            z_scores.get("data_drift"), baseline_mean.get("data_drift"),
            baseline_quality.get("data_drift", {}).get("is_stable", True), is_learning
        )
        render_metric_with_translation(
            "6. Infrastructure Change (var)", "infrastructure_change", metrics.get("infrastructure_change", 0),
            z_scores.get("infrastructure_change"), baseline_mean.get("infrastructure_change"),
            baseline_quality.get("infrastructure_change", {}).get("is_stable", True), is_learning
        )
        render_metric_with_translation(
            "9. Event Traffic (count)", "event_traffic", metrics.get("event_traffic", 0),
            z_scores.get("event_traffic"), baseline_mean.get("event_traffic"),
            baseline_quality.get("event_traffic", {}).get("is_stable", True), is_learning, fmt=".0f"
        )
        
    # --- Baseline Threshold Status Card ---
    if baseline_status:
        st.markdown("---")
        st.subheader("Dynamic Threshold Status")
        
        b_mode = baseline_status.get("mode", "learning")
        samples = baseline_status.get("sample_size", 0)
        req_samples = baseline_status.get("required_samples", 30)
        prog = baseline_status.get("learning_progress_percent", 0)
        
        if b_mode == "learning":
            mode_badge = f"<span style='background:#f59e0b; color:white; padding:4px 10px; border-radius:9999px; font-weight:bold; font-size:12px;'>Learning ({samples}/{req_samples})</span>"
        else:
            mode_badge = "<span style='background:#10b981; color:white; padding:4px 10px; border-radius:9999px; font-weight:bold; font-size:12px;'>Active — learned thresholds</span>"
            
        st.markdown(f"{mode_badge}", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        
        if b_mode == "learning":
            st.progress(prog / 100.0, text="Calibrating initial baseline thresholds...")
        else:
            b_col1, b_col2 = st.columns(2)
            with b_col1:
                st.markdown(f"**High congestion at: {baseline_status.get('high_threshold', 0):.2f}**")
                st.caption(f"Learned from {samples} observations. Original: {baseline_status.get('original_high_threshold', 0):.2f}")
                
            with b_col2:
                st.markdown(f"**Medium congestion at: {baseline_status.get('medium_threshold', 0):.2f}**")
                st.caption(f"Learned from {samples} observations. Original: {baseline_status.get('original_medium_threshold', 0):.2f}")
                
            if baseline_status.get("threshold_floors_applied", False):
                st.warning("Floor applied — baseline computed a lower threshold but safety minimum enforced")
            if baseline_status.get("threshold_ceilings_applied", False):
                st.warning("Ceiling applied — baseline computed a higher threshold but safety maximum enforced")

    # ===================================================================
    # FEATURE 4: Drift Injection / What-If Simulation
    # ===================================================================
    st.markdown("---")
    st.header("🧪 Drift Injection / What-If Simulation")
    st.markdown(
        '<p style="color:#94a3b8; font-size:14px; margin-top:-10px;">'
        'Adjust parameters to observe how Sentinel responds in real time</p>',
        unsafe_allow_html=True,
    )

    # --- Controls ---
    sim_col1, sim_col2 = st.columns(2)
    with sim_col1:
        sim_traffic = st.slider(
            "Traffic Volume", min_value=100, max_value=600,
            value=298, step=10, key="sim_traffic",
        )
        sim_accident = st.toggle("Accident Active", value=False, key="sim_accident")
    with sim_col2:
        sim_lanes = st.slider(
            "Active Lanes", min_value=1, max_value=6,
            value=3, step=1, key="sim_lanes",
        )
        sim_event = st.toggle("Event Traffic Surge", value=False, key="sim_event")

    # Auto-run: detect any parameter change and auto-trigger simulation
    _sim_params = (sim_traffic, sim_lanes, sim_accident, sim_event)
    _prev_params = st.session_state.get("_prev_sim_params")

    auto_triggered = False
    if _prev_params is not None and _prev_params != _sim_params:
        auto_triggered = True
    st.session_state["_prev_sim_params"] = _sim_params

    run_clicked = st.button("🚀 Run Simulation", type="primary", use_container_width=True, key="run_sim")

    if auto_triggered:
        st.caption("⏳ Recalculating…")

    if run_clicked or auto_triggered:
        with st.spinner("Running simulation…"):
            try:
                sim_res = requests.post(
                    f"{API_URL}/simulate-drift",
                    json={
                        "traffic_volume": sim_traffic,
                        "active_lanes": sim_lanes,
                        "accident_active": sim_accident,
                        "event_traffic_active": sim_event,
                    },
                    timeout=15,
                )
                sim_data = sim_res.json()
            except Exception as e:
                st.error(f"Simulation request failed: {e}")
                sim_data = None

        if sim_data and "error" not in sim_data:
            st.session_state["sim_result"] = sim_data

    # --- Render results if available ---
    sim_data = st.session_state.get("sim_result")
    if sim_data:
        b_metrics = sim_data["baseline_metrics"]
        s_metrics = sim_data["simulated_metrics"]
        b_alerts = sim_data["baseline_alerts"]
        s_alerts = sim_data["simulated_alerts"]
        newly = sim_data["newly_triggered"]
        resolved = sim_data.get("resolved_by_simulation", [])

        # --- Summary banner ---
        if newly:
            alert_names = ", ".join([n.replace("_", " ").title() for n in newly])
            st.error(f"🚨 Simulation triggered **{len(newly)}** new drift alert(s): **{alert_names}**")
        else:
            st.success("✅ No new drift detected under these conditions. System is stable.")

        if resolved:
            resolved_names = ", ".join([n.replace("_", " ").title() for n in resolved])
            st.info(f"🔧 Simulation resolved {len(resolved)} alert(s): **{resolved_names}**")

        # --- Split comparison ---
        left, right = st.columns(2)

        METRIC_LABELS = {
            "behaviour_adaptation": "1. Behaviour Adaptation",
            "data_bias": "2. Data Bias",
            "data_drift": "3. Data Drift",
            "feedback_loop": "4. Feedback Loop",
            "silent_drift": "5. Silent Drift",
            "infrastructure_change": "6. Infrastructure Change",
            "policy_change": "7. Policy Change",
            "technology_influence": "8. Technology Influence",
            "event_traffic": "9. Event Traffic",
        }

        def _badge(text: str, color: str) -> str:
            return (
                f'<span style="background:{color}; color:white; padding:2px 8px; '
                f'border-radius:9999px; font-size:11px; font-weight:600; '
                f'margin-left:8px;">{text}</span>'
            )

        with left:
            st.markdown("#### 📊 Baseline (last 500 real decisions)")
            for key, label in METRIC_LABELS.items():
                val = b_metrics.get(key, 0.0)
                is_alert = key in b_alerts
                badge = _badge("ALERT", "#ef4444") if is_alert else _badge("OK", "#22c55e")
                fmt_val = f"{val:.4f}" if key not in ("technology_influence", "event_traffic") else f"{val:.0f}"
                st.markdown(
                    f'<p style="margin:4px 0; font-size:14px;">'
                    f'<strong>{label}</strong>: {fmt_val} {badge}</p>',
                    unsafe_allow_html=True,
                )

        with right:
            st.markdown("#### 🧪 Simulated (with your parameters)")
            for key, label in METRIC_LABELS.items():
                val = s_metrics.get(key, 0.0)
                b_val = b_metrics.get(key, 0.0)
                is_new_alert = key in newly
                is_alert = key in s_alerts
                changed = abs(val - b_val) > 1e-6

                if is_new_alert:
                    badge = _badge("NEW ALERT", "#ef4444")
                elif is_alert:
                    badge = _badge("ALERT", "#ef4444")
                else:
                    badge = _badge("OK", "#22c55e")

                highlight = ' style="color:#f59e0b;"' if changed and not is_new_alert else ""
                fmt_val = f"{val:.4f}" if key not in ("technology_influence", "event_traffic") else f"{val:.0f}"

                st.markdown(
                    f'<p style="margin:4px 0; font-size:14px;">'
                    f'<strong{highlight}>{label}</strong>: {fmt_val} {badge}</p>',
                    unsafe_allow_html=True,
                )

        # --- Plain-English translations for changed metrics ---
        changed_keys = [k for k in METRIC_LABELS if abs(s_metrics.get(k, 0) - b_metrics.get(k, 0)) > 1e-6]
        if changed_keys:
            st.markdown("---")
            st.markdown("##### 💬 What changed (plain English)")
            for key in changed_keys:
                translation = get_translation(key, s_metrics.get(key, 0))
                label = METRIC_LABELS[key]
                st.markdown(
                    f'<p style="color:#94a3b8; font-size:13px; margin:2px 0;">'
                    f'<strong style="color:#e2e8f0;">{label}:</strong> {translation}</p>',
                    unsafe_allow_html=True,
                )

    # Charts for visualization context
    if logs:

        st.markdown("---")
        st.subheader("Contextual Analytics")
        df = pd.DataFrame(logs)
        df['event_time'] = pd.to_datetime(df['event_time'])

        c1, c2 = st.columns(2)
        with c1:
            fig_scatter = px.scatter(df, x='traffic', y='active_lanes', color='congestion_level',
                                    title='AI Decision Mapping (Traffic vs Lanes)', template='plotly_dark')
            st.plotly_chart(fig_scatter, use_container_width=True)

        with c2:
            event_counts = df['reason'].value_counts().reset_index()
            event_counts.columns = ['Reason', 'Count']
            fig_pie = px.pie(event_counts, values='Count', names='Reason',
                             title='Event Distribution Triggering AI Behaviour', template='plotly_dark')
            st.plotly_chart(fig_pie, use_container_width=True)

    # ===================================================================
    # FEATURE 3: Audit Log
    # ===================================================================
    st.markdown("---")
    st.header("📜 Audit Log")

    # Fetch audit data
    audit_rows = []
    try:
        audit_res = requests.get(f"{API_URL}/audit", timeout=5)
        if audit_res.status_code == 200:
            audit_rows = audit_res.json().get("audit_log", [])
    except Exception as e:
        st.error(f"Error fetching audit log: {e}")

    if not audit_rows:
        st.info("No audit records found yet. Resolved alerts will appear here.")
    else:
        # ---------------------------------------------------------------
        # Filters
        # ---------------------------------------------------------------
        filter_col1, filter_col2, filter_col3 = st.columns([1, 1, 2])

        all_types = sorted({r.get("alert_type", "—") or "—" for r in audit_rows})
        with filter_col1:
            sev_filter = st.selectbox("Filter by Severity", ["All", "High", "Medium", "Low"], key="sev_filter")
        with filter_col2:
            type_filter = st.selectbox("Filter by Alert Type", ["All"] + all_types, key="type_filter")
        with filter_col3:
            date_range = st.date_input(
                "Date range",
                value=[],
                key="date_filter",
            )

        # Apply filters
        filtered = audit_rows
        if sev_filter != "All":
            filtered = [r for r in filtered if SEVERITY_MAP.get(r.get("alert_type", ""), "Medium") == sev_filter]
        if type_filter != "All":
            filtered = [r for r in filtered if (r.get("alert_type") or "—") == type_filter]
        if date_range and len(date_range) == 2:
            start_d, end_d = date_range
            filtered = [
                r for r in filtered
                if r.get("resolved_at") and start_d <= datetime.datetime.fromisoformat(r["resolved_at"][:10]).date() <= end_d
            ]

        # ---------------------------------------------------------------
        # Pagination
        # ---------------------------------------------------------------
        PAGE_SIZE = 10
        total_pages = max(1, (len(filtered) + PAGE_SIZE - 1) // PAGE_SIZE)
        if st.session_state.audit_page >= total_pages:
            st.session_state.audit_page = total_pages - 1

        start_idx = st.session_state.audit_page * PAGE_SIZE
        page_rows = filtered[start_idx : start_idx + PAGE_SIZE]

        # ---------------------------------------------------------------
        # Render table as styled HTML
        # ---------------------------------------------------------------
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
            .audit-table { width:100%; border-collapse:collapse; font-family:'Inter',sans-serif; font-size:13px; }
            .audit-table th { background:#1e293b; color:#e2e8f0; padding:10px 8px; text-align:left; border-bottom:2px solid #334155; }
            .audit-table td { padding:8px; border-bottom:1px solid #334155; color:#cbd5e1; }
            .audit-table tr:hover td { background:#1e293b; }
        </style>
        <table class="audit-table">
        <thead><tr>
            <th>Alert ID</th><th>Alert Type</th><th>Severity</th><th>Description</th>
            <th>Created At</th><th>Ack</th><th>Resolved</th><th>Operator Notes</th><th>Action Taken</th>
        </tr></thead><tbody>
        """

        for row in page_rows:
            alert_id = str(row.get("id", ""))[:8]
            a_type = row.get("alert_type") or "—"
            severity = SEVERITY_MAP.get(a_type, "Medium")
            desc = row.get("alert_text") or "—"
            created = (row.get("resolved_at") or "—")[:19]
            status = row.get("status", "")
            is_ack = status in ("ACKNOWLEDGED", "RESOLVED")
            is_resolved = status == "RESOLVED"
            notes = row.get("operator_notes") or ""
            action = _derive_action(status)

            table_html += f"""<tr>
                <td><code>{alert_id}</code></td>
                <td>{a_type}</td>
                <td>{build_badge(severity)}</td>
                <td>{desc}</td>
                <td>{created}</td>
                <td style="text-align:center;">{build_check(is_ack)}</td>
                <td style="text-align:center;">{build_check(is_resolved)}</td>
                <td>{notes}</td>
                <td>{action}</td>
            </tr>"""

        table_html += "</tbody></table>"

        st.markdown(table_html, unsafe_allow_html=True)

        # ---------------------------------------------------------------
        # Pagination controls
        # ---------------------------------------------------------------
        pcol1, pcol2, pcol3 = st.columns([1, 2, 1])
        with pcol1:
            if st.button("← Previous", disabled=(st.session_state.audit_page == 0), key="prev_page"):
                st.session_state.audit_page -= 1
                st.rerun()
        with pcol2:
            st.markdown(
                f"<p style='text-align:center; color:#94a3b8;'>Page {st.session_state.audit_page + 1} of {total_pages} "
                f"({len(filtered)} records)</p>",
                unsafe_allow_html=True,
            )
        with pcol3:
            if st.button("Next →", disabled=(st.session_state.audit_page >= total_pages - 1), key="next_page"):
                st.session_state.audit_page += 1
                st.rerun()

        # ---------------------------------------------------------------
        # PDF Export
        # ---------------------------------------------------------------
        st.markdown("<br>", unsafe_allow_html=True)
        pdf_bytes = generate_audit_pdf(filtered, metrics)
        filename = f"sentinel_audit_report_{datetime.datetime.now().strftime('%Y-%m-%d')}.pdf"
        st.download_button(
            label="📄 Export PDF Report",
            data=pdf_bytes,
            file_name=filename,
            mime="application/pdf",
            type="primary",
        )
