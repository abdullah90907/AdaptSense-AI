"""Install the bundled Victoria evidence into the configured SQLite database."""
import gzip
import json
from contextlib import closing

from app.demo import DEMO_DIR
from app.main import connection


def seed_demo():
    with gzip.open(DEMO_DIR / "victoria-demo.json.gz", "rt", encoding="utf-8") as source:
        records = json.load(source)["records"]
    inserted = 0
    with closing(connection()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        for record in records:
            key, kind, body = record["id"], record["kind"], record["body"]
            existing = db.execute("SELECT kind, body FROM records WHERE id=?", (key,)).fetchone()
            if existing:
                previous = json.loads(existing[1])
                if kind == "adaptive_experiment":
                    previous.pop("worker", None)
                if existing[0] != kind or previous != body:
                    raise ValueError(f"Victoria demo record {key} conflicts with an existing record")
                continue
            db.execute("INSERT INTO records VALUES (?, ?, ?)", (key, kind, json.dumps(body, allow_nan=False)))
            inserted += 1
    return inserted


if __name__ == "__main__":
    print(f"Victoria demo ready. Inserted {seed_demo()} records.")
