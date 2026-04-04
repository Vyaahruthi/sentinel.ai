import os
from google import genai
from google.genai import types
import json

def get_explanation(alerts: list, metrics: dict) -> dict:
    """
    Calls Gemini API to explain the detected anomalies.
    Returns: { "cause": ..., "reasons": [...], "recommended_actions": [...] }
    """
    if not alerts:
        return {
            "cause": "Normal operation",
            "reasons": ["All metrics are within expected thresholds."],
            "recommended_actions": ["Continue monitoring."]
        }
        
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {
            "cause": "API Key Missing",
            "reasons": ["GEMINI_API_KEY is not set in the environment."],
            "recommended_actions": ["Provide a valid Gemini API key in the .env file."]
        }
        
    try:
        client = genai.Client(api_key=api_key)
        
        alerts_str = ", ".join(alerts)
        metrics_str = json.dumps({k: round(v, 4) for k, v in metrics.items()})
        
        prompt = f"""
        You are 'Sentinel AI', an advanced AI watchdog supervising a Smart-City Adaptive Traffic Control System.
        
        The monitoring engine has detected the following threshold breaches (Alerts):
        {alerts_str}
        
        Current drift metrics:
        {metrics_str}
        
        Explain the anomaly based on traffic engineering principles. Provide your response as a valid JSON object EXACTLY matching this schema (do not include markdown block formatting, just the raw JSON):
        {{
            "cause": "A single sentence identifying the root cause of the drift.",
            "reasons": ["Reason 1", "Reason 2"],
            "recommended_actions": ["Action 1", "Action 2", "Action 3"]
        }}
        """
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        
        text = response.text.strip()
        if text.startswith('```json'):
            text = text[7:]
        if text.endswith('```'):
            text = text[:-3]
            
        return json.loads(text.strip())
        
    except Exception as e:
        print(f"Error fetching explanation from Gemini: {e}")
        return {
            "cause": "Error generating explanation",
            "reasons": [str(e)],
            "recommended_actions": ["Check system logs", "Verify Gemini API connectivity"]
        }
