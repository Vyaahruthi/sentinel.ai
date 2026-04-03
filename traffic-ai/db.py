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
                raise EnvironmentError(
                    "SUPABASE_URL and SUPABASE_KEY must be set in environment variables."
                )

            cls._instance = create_client(url, key)

        return cls._instance


def get_db_client() -> Client:
    """Returns the singleton Supabase client"""
    return SupabaseSingleton.get_client()