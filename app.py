"""
FastAPI app for Show Taste Matcher.

Usage:
    python3 -m uvicorn app:app --reload
Then open http://127.0.0.1:8000 in your browser.
"""

import os
import requests
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from recommender import search_shows, get_recommendations
from data_utils import ensure_show_in_db

load_dotenv()
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = ""):
    results = search_shows(q) if q.strip() else []
    return templates.TemplateResponse(
        "partials/search_results.html", {"request": request, "results": results}
    )


def fetch_trailer_key(show_id: int):
    try:
        resp = requests.get(
            f"https://api.themoviedb.org/3/tv/{show_id}/videos",
            params={"api_key": TMDB_API_KEY},
            timeout=5,
        )
        resp.raise_for_status()
        for video in resp.json().get("results", []):
            if video.get("site") == "YouTube" and video.get("type") == "Trailer":
                return video["key"]
    except Exception:
        pass
    return None


@app.post("/recommend", response_class=HTMLResponse)
def recommend(request: Request, show_ids: str = Form(...)):
    ids = [int(x) for x in show_ids.split(",") if x.strip()]
    for show_id in ids:
        ensure_show_in_db(show_id)
    recs = get_recommendations(ids)
    for r in recs:
        r["trailer_key"] = fetch_trailer_key(r["id"])
    return templates.TemplateResponse(
        "partials/recommendations.html", {"request": request, "recommendations": recs}
    )
