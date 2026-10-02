"""
Generate a short thematic tag summary for each show using a local LLM via
Ollama (free, runs on your own machine), and cache it in a new column in
shows.duckdb so this only runs once per show.

Requires Ollama installed and running: https://ollama.com
Then pull a small model once:
    ollama pull llama3.2

Usage:
    python3 generate_thematic_tags.py
"""

import time
import duckdb
import requests

DB_PATH = "shows.duckdb"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3"  # matches what's already pulled via `ollama list`


def ensure_tags_column(con):
    """Add a thematic_tags column if it doesn't already exist."""
    existing = [row[1] for row in con.execute("PRAGMA table_info(shows)").fetchall()]
    if "thematic_tags" not in existing:
        con.execute("ALTER TABLE shows ADD COLUMN thematic_tags VARCHAR")


def generate_tags(name: str, overview: str, genres: str) -> str:
    """Ask the local model for a short comma-separated thematic tag summary."""
    prompt = (
        f"Show: {name}\n"
        f"Genres: {genres}\n"
        f"Overview: {overview}\n\n"
        "In 4-6 short comma-separated tags, describe this show's tone, themes, "
        "and character dynamics (e.g. 'slow-burn, morally gray protagonist, "
        "ensemble cast, workplace tension'). Reply with ONLY the tags, nothing else."
    )
    resp = requests.post(
        OLLAMA_URL,
        json={"model": MODEL, "prompt": prompt, "stream": False},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["response"].strip()


def main():
    con = duckdb.connect(DB_PATH)
    ensure_tags_column(con)

    rows = con.execute("""
        SELECT id, name, overview, genres FROM shows
        WHERE thematic_tags IS NULL
    """).fetchall()

    if not rows:
        print("All shows already have thematic tags. Nothing to do.")
        con.close()
        return

    print(f"Generating tags for {len(rows)} shows using local model '{MODEL}'...")
    print("(First run may be slow while Ollama loads the model into memory.)")

    for i, (show_id, name, overview, genres) in enumerate(rows, start=1):
        try:
            tags = generate_tags(name, overview or "", genres or "")
            con.execute(
                "UPDATE shows SET thematic_tags = ? WHERE id = ?",
                [tags, show_id],
            )
        except requests.exceptions.ConnectionError:
            print("\nCouldn't reach Ollama. Is it running? Try: ollama serve")
            break
        except Exception as e:
            print(f"  skipped {name}: {e}")
        if i % 10 == 0:
            print(f"  {i}/{len(rows)} done")

    con.close()
    print("Done. Tags are cached in shows.duckdb — re-running this script won't redo existing shows.")


if __name__ == "__main__":
    main()
