"""
Utilities for fetching a show from TMDb on-demand and generating its
thematic tags via Ollama, then caching it — so searching for ANY show works,
not just ones already pulled by build_show_database.py.
"""

import os
import requests
import duckdb
from dotenv import load_dotenv

load_dotenv()

TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w342"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3"
DB_PATH = "shows.duckdb"


def tmdb_get(path, params=None):
    params = params or {}
    params["api_key"] = TMDB_API_KEY
    resp = requests.get(f"{TMDB_BASE_URL}{path}", params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def search_tmdb_live(query, limit=8):
    data = tmdb_get("/search/tv", {"query": query})
    results = data.get("results", [])[:limit]
    return [
        {
            "id": r["id"],
            "name": r.get("name"),
            "poster_url": f"{TMDB_IMAGE_BASE}{r['poster_path']}" if r.get("poster_path") else None,
        }
        for r in results
    ]


def fetch_show_details(show_id):
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


def generate_tags(name, overview, genres):
    prompt = (
        f"Show: {name}\nGenres: {genres}\nOverview: {overview}\n\n"
        "In 4-6 short comma-separated tags, describe this show's tone, themes, "
        "and character dynamics (e.g. 'slow-burn, morally gray protagonist, "
        "ensemble cast, workplace tension'). Reply with ONLY the tags, nothing else."
    )
    resp = requests.post(
        OLLAMA_URL,
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["response"].strip()


def ensure_show_in_db(show_id):
    con = duckdb.connect(DB_PATH)
    row = con.execute("SELECT thematic_tags FROM shows WHERE id = ?", [show_id]).fetchone()

    if row and row[0]:
        con.close()
        return

    show = fetch_show_details(show_id)
    tags = generate_tags(show["name"], show["overview"] or "", show["genres"] or "")

    if row:
        con.execute("UPDATE shows SET thematic_tags = ? WHERE id = ?", [tags, show_id])
    else:
        con.execute("""
            INSERT INTO shows (id, name, overview, poster_path, vote_average, vote_count,
                first_air_date, genres, keywords, top_cast, thematic_tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            show["id"], show["name"], show["overview"], show["poster_path"],
            show["vote_average"], show["vote_count"], show["first_air_date"],
            show["genres"], show["keywords"], show["top_cast"], tags,
        ])

    con.close()
