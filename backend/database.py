import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

class SupabaseSingleton:
    _instance = None

    @classmethod
    def get_client(cls) -> Client:
        if cls._instance is None:
            url: str = os.environ.get("SUPABASE_URL", "")
            key: str = os.environ.get("SUPABASE_KEY", "")

            if not url or not key:
                print("Missing SUPABASE_URL or SUPABASE_KEY in environment.")
                return None

            cls._instance = create_client(url, key)

        return cls._instance

def get_db_client() -> Client:
    """Returns the singleton Supabase client"""
    return SupabaseSingleton.get_client()

supabase = get_db_client()

def get_recent_logs(limit: int = 500):
    if not supabase: return []
    try:
        response = supabase.table('traffic_logs').select('*').order('event_time', desc=True).limit(limit).execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching logs: {e}")
        return []

def insert_threshold_history(data: dict):
    if not supabase: return None
    try:
        response = supabase.table('threshold_history').insert(data).execute()
        return response
    except Exception as e:
        print(f"Error inserting threshold history: {e}")
        return None

def get_recent_threshold_history(limit: int = 200):
    if not supabase: return []
    try:
        response = supabase.table('threshold_history').select('*').order('computed_at', desc=True).limit(limit).execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching threshold history: {e}")
        return []

def get_baseline_state():
    if not supabase:
        return {
            "run_count": 0, "baseline_locked": False,
            "baseline_mean": {}, "baseline_std": {},
            "baseline_quality": {}, "baseline_min_runs": 30
        }
    try:
        response = supabase.table('sentinel_baseline').select('*').limit(1).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]
            
        initial_row = {
            "id": '00000000-0000-0000-0000-000000000001',
            "run_count": 0,
            "baseline_locked": False,
            "baseline_mean": {},
            "baseline_std": {},
            "baseline_min_runs": 30,
            "baseline_quality": {}
        }
        supabase.table("sentinel_baseline").insert(initial_row).execute()
        return initial_row
    except Exception as e:
        print(f"Error fetching baseline state: {e}")
        return {
            "run_count": 0, "baseline_locked": False,
            "baseline_mean": {}, "baseline_std": {},
            "baseline_quality": {}, "baseline_min_runs": 30
        }

def upsert_baseline_state(data: dict):
    if not supabase: return None
    try:
        row_id = data.get("id", "00000000-0000-0000-0000-000000000001")
        response = supabase.table('sentinel_baseline').update(data).eq("id", row_id).execute()
        return response
    except Exception as e:
        print(f"Error upserting baseline state: {e}")
        return None

def get_resolved_alerts():
    if not supabase: return []
    try:
        response = supabase.table('alert_resolutions').select('alert_text, alert_type, status').execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching resolved alerts: {e}")
        return []

def get_all_resolutions():
    if not supabase: return []
    try:
        response = supabase.table('alert_resolutions').select('*').order('resolved_at', desc=True).execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching all resolutions: {e}")
        return []

def insert_alert_resolution(data: dict):
    if not supabase: return None
    try:
        response = supabase.table('alert_resolutions').insert(data).execute()
        return response
    except Exception as e:
        print(f"Error inserting alert resolution: {e}")
        return None