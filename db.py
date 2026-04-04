import os
from supabase import create_client
from dotenv import load_dotenv

# Try to load environment variables from .env if present
load_dotenv(os.path.join(os.path.dirname(__file__), '..', 'traffic-ai', '.env'))
load_dotenv() 

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

if not url or not key:
    raise ValueError("Missing Supabase credentials (SUPABASE_URL, SUPABASE_KEY)")

client = create_client(url, key)
