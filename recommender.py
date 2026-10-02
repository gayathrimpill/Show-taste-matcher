"""
Shared recommendation logic, used by the FastAPI app.
"""

import duckdb
import numpy as np
from functools import lru_cache
from sentence_transformers import SentenceTransformer

@lru_cache(maxsize=1)
def get_model():
    return SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
    
DB_PATH = "shows.duckdb"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w342"
GENRE_WEIGHT = 0.3
TAG_WEIGHT = 0.7


def load_all_shows():
    con = duckdb.connect(DB_PATH)
    rows = con.execute("""
        SELECT id, name, overview, poster_path, vote_average,
               genres, keywords, top_cast, thematic_tags
        FROM shows
        WHERE thematic_tags IS NOT NULL
    """).fetchall()
    con.close()
    columns = ["id", "name", "overview", "poster_path", "vote_average",
               "genres", "keywords", "top_cast", "thematic_tags"]
    return [dict(zip(columns, row)) for row in rows]


def search_local_shows(query, limit=12):
    con = duckdb.connect(DB_PATH)
    rows = con.execute("""
        SELECT id, name, poster_path FROM shows
        WHERE (name ILIKE ? OR genres ILIKE ?) AND thematic_tags IS NOT NULL
        LIMIT ?
    """, [f"%{query}%", f"%{query}%", limit]).fetchall()
    con.close()
    return [
        {"id": r[0], "name": r[1], "poster_url": f"{TMDB_IMAGE_BASE}{r[2]}" if r[2] else None}
        for r in rows
    ]


def search_shows(query, limit=12):
    from data_utils import search_tmdb_live

    local_results = search_local_shows(query, limit)
    local_ids = {r["id"] for r in local_results}

    remaining = limit - len(local_results)
    if remaining <= 0:
        return local_results

    live_results = search_tmdb_live(query, limit=remaining + len(local_ids))
    new_results = [r for r in live_results if r["id"] not in local_ids][:remaining]

    return local_results + new_results


def genre_overlap_score(genres_a, genres_b):
    set_a = set(g.strip() for g in (genres_a or "").split(",") if g.strip())
    set_b = set(g.strip() for g in (genres_b or "").split(",") if g.strip())
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def get_recommendations(favorite_ids, top_n=10):
    shows = load_all_shows()
    favorites = [s for s in shows if s["id"] in favorite_ids]
    if not favorites:
        return []

    model = get_model()
    all_tags = [s["thematic_tags"] for s in shows]
    embeddings = model.encode(all_tags, normalize_embeddings=True)

    favorite_indices = [i for i, s in enumerate(shows) if s["id"] in favorite_ids]
    profile = embeddings[favorite_indices].mean(axis=0)
    profile = profile / np.linalg.norm(profile)
    semantic_scores = embeddings @ profile

    results = []
    for i, show in enumerate(shows):
        if show["id"] in favorite_ids:
            continue
        best_genre = max(genre_overlap_score(f["genres"], show["genres"]) for f in favorites)
        blended = TAG_WEIGHT * semantic_scores[i] + GENRE_WEIGHT * best_genre
        results.append({
            **show,
            "score": float(blended),
            "poster_url": f"{TMDB_IMAGE_BASE}{show['poster_path']}" if show["poster_path"] else None,
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_n]
