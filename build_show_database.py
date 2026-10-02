"""
Phase 1 — Data layer: pull TV show data from TMDb and store it in DuckDB.

Usage:
    export TMDB_API_KEY="f70c5425d9671661d75ca2c7103a02e3"
    python build_show_database.py

This pulls popular + top-rated TV shows, fetches full details for each
(genres, keywords, cast, overview, poster path), and writes them into a
local DuckDB file (shows.duckdb) that the rest of the project queries
with SQL instead of hitting TMDb live every time.
"""

import os
import time
from typing import Optional
import requests
import duckdb

TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
BASE_URL = "https://api.themoviedb.org/3"
DB_PATH = "shows.duckdb"

# How many pages of "popular" and "top rated" to pull (20 shows per page).
# Start small while testing, then bump this up.
PAGES_PER_LIST = 5


def tmdb_get(path: str, params: Optional[dict] = None) -> dict:
    """Thin wrapper around a TMDb GET request."""
    params = params or {}
    params["api_key"] = TMDB_API_KEY
    resp = requests.get(f"{BASE_URL}{path}", params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_show_ids(list_type: str, pages: int) -> list[int]:
    """Fetch show IDs from a TMDb list endpoint (e.g. 'popular', 'top_rated')."""
    ids = []
    for page in range(1, pages + 1):
        data = tmdb_get(f"/tv/{list_type}", {"page": page})
        ids.extend(show["id"] for show in data.get("results", []))
        time.sleep(0.25)  # stay comfortably under TMDb's rate limit
    return ids


def fetch_show_details(show_id: int) -> dict:
    """Fetch full details for one show: genres, keywords, overview, poster, etc."""
    details = tmdb_get(f"/tv/{show_id}", {"append_to_response": "keywords,credits"})

    genres = [g["name"] for g in details.get("genres", [])]
    keywords = [k["name"] for k in details.get("keywords", {}).get("results", [])]
    cast = [c["name"] for c in details.get("credits", {}).get("cast", [])[:5]]

    return {
        "id": details["id"],
        "name": details.get("name"),
        "overview": details.get("overview"),
        "poster_path": details.get("poster_path"),
        "vote_average": details.get("vote_average"),
        "vote_count": details.get("vote_count"),
        "first_air_date": details.get("first_air_date"),
        "genres": ", ".join(genres),
        "keywords": ", ".join(keywords),
        "top_cast": ", ".join(cast),
    }


def build_database(shows: list[dict]) -> None:
    """Create (or replace) the shows table in DuckDB and load the data."""
    con = duckdb.connect(DB_PATH)
    con.execute("DROP TABLE IF EXISTS shows")
    con.execute("""
        CREATE TABLE shows (
            id INTEGER PRIMARY KEY,
            name VARCHAR,
            overview VARCHAR,
            poster_path VARCHAR,
            vote_average DOUBLE,
            vote_count INTEGER,
            first_air_date VARCHAR,
            genres VARCHAR,
            keywords VARCHAR,
            top_cast VARCHAR
        )
    """)

    con.executemany(
        """
        INSERT INTO shows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                s["id"], s["name"], s["overview"], s["poster_path"],
                s["vote_average"], s["vote_count"], s["first_air_date"],
                s["genres"], s["keywords"], s["top_cast"],
            )
            for s in shows
        ],
    )
    con.close()


def main():
    if not TMDB_API_KEY:
        raise SystemExit("Set the TMDB_API_KEY environment variable first.")

    print("Fetching show IDs from popular + top rated lists...")
    ids = set(fetch_show_ids("popular", PAGES_PER_LIST))
    ids.update(fetch_show_ids("top_rated", PAGES_PER_LIST))
    print(f"Found {len(ids)} unique shows. Fetching details...")

    shows = []
    for i, show_id in enumerate(ids, start=1):
        try:
            shows.append(fetch_show_details(show_id))
        except requests.HTTPError as e:
            print(f"  skipped {show_id}: {e}")
        if i % 20 == 0:
            print(f"  {i}/{len(ids)} done")
        time.sleep(0.25)

    print(f"Writing {len(shows)} shows to {DB_PATH}...")
    build_database(shows)
    print("Done. Try: duckdb shows.duckdb -c 'SELECT name, genres FROM shows LIMIT 5;'")


if __name__ == "__main__":
    main()
