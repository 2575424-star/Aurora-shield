import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from statistics import median
from typing import Literal
from fastapi import FastAPI, HTTPException, Query, Header, Depends
from pydantic import BaseModel, Field, HttpUrl

app = FastAPI(title="Realty Monitor", version="0.1.0")
DB = os.getenv("DATABASE_PATH", "realty.db")
API_KEY = os.getenv("REALTY_API_KEY")

def require_key(x_api_key: str | None = Header(default=None)):
    if not API_KEY or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Valid X-API-Key required")

@contextmanager
def connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS listings (
          source TEXT NOT NULL, external_id TEXT NOT NULL, url TEXT NOT NULL,
          city TEXT NOT NULL, district TEXT, rooms INTEGER NOT NULL,
          market TEXT NOT NULL, area REAL NOT NULL, price INTEGER NOT NULL,
          first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
          PRIMARY KEY(source,external_id))""")
        db.execute("""CREATE TABLE IF NOT EXISTS price_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
          external_id TEXT NOT NULL, price INTEGER NOT NULL, seen_at TEXT NOT NULL)""")

init_db()

class Listing(BaseModel):
    source: Literal["avito", "cian"]
    external_id: str = Field(min_length=1, max_length=128)
    url: HttpUrl
    city: str = Field(min_length=1)
    district: str | None = None
    rooms: int = Field(ge=0, le=20)
    market: Literal["secondary", "new"] = "secondary"
    area: float = Field(gt=0, le=10000)
    price: int = Field(gt=0)

@app.get("/health")
def health():
    return {"status": "ok", "ingestion": "manual_or_external_only"}

@app.post("/listings")
def upsert(item: Listing, _auth: None = Depends(require_key)):
    now = datetime.now(timezone.utc).isoformat()
    data = item.model_dump(mode="json")
    with connect() as db:
        old = db.execute("SELECT price FROM listings WHERE source=? AND external_id=?", (item.source,item.external_id)).fetchone()
        if old:
            db.execute("UPDATE listings SET url=?,city=?,district=?,rooms=?,market=?,area=?,price=?,last_seen=? WHERE source=? AND external_id=?",
              (data["url"],item.city,item.district,item.rooms,item.market,item.area,item.price,now,item.source,item.external_id))
        else:
            db.execute("INSERT INTO listings VALUES (?,?,?,?,?,?,?,?,?,?,?)",
              (item.source,item.external_id,data["url"],item.city,item.district,item.rooms,item.market,item.area,item.price,now,now))
        if old is None or old["price"] != item.price:
            db.execute("INSERT INTO price_history(source,external_id,price,seen_at) VALUES (?,?,?,?)",
              (item.source,item.external_id,item.price,now))
    return {"status":"updated" if old else "created", "price_changed":old is not None and old["price"] != item.price}

def enriched(rows):
    result=[]
    for r in rows:
        item=dict(r)
        peers=[p["price"]/p["area"] for p in rows if p["city"]==r["city"] and p["rooms"]==r["rooms"] and p["market"]==r["market"] and p["district"]==r["district"] and (p["source"],p["external_id"])!=(r["source"],r["external_id"])]
        price_sqm=r["price"]/r["area"]
        benchmark=median(peers) if len(peers)>=5 else None
        item.update(price_sqm=round(price_sqm), benchmark_sqm=round(benchmark) if benchmark else None,
                    discount_pct=round(100*(1-price_sqm/benchmark),1) if benchmark else None, comparable_count=len(peers))
        result.append(item)
    return result

@app.get("/listings")
def listings(city: str | None = None, min_discount: float | None = Query(None, ge=0, le=100)):
    with connect() as db:
        rows=db.execute("SELECT * FROM listings").fetchall()
    items=enriched(rows)
    if city: items=[x for x in items if x["city"].casefold()==city.casefold()]
    if min_discount is not None: items=[x for x in items if x["discount_pct"] is not None and x["discount_pct"]>=min_discount]
    return {"count":len(items), "items":items}

@app.get("/listings/{source}/{external_id}/history")
def history(source: str, external_id: str):
    with connect() as db:
        rows=db.execute("SELECT price,seen_at FROM price_history WHERE source=? AND external_id=? ORDER BY seen_at", (source,external_id)).fetchall()
    if not rows: raise HTTPException(404,"Listing not found")
    return {"history":[dict(r) for r in rows]}

@app.get("/stats")
def stats():
    with connect() as db:
        total=db.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        changes=db.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    return {"listings":total,"price_observations":changes}
