# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Dict, Any, Optional
import os, math, logging, requests

GOOGLE_KEY = os.getenv("GOOGLE_PLACES_API_KEY")

# 키가 없으면 바로 오류
if not GOOGLE_KEY:
    raise RuntimeError("❌ GOOGLE_PLACES_API_KEY 환경변수가 설정되어 있지 않습니다!")

def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return round(2 * R * math.asin(math.sqrt(a)), 2)

def _text_search(name: str, lat: float, lon: float) -> Optional[str]:
    if not name:
        return None
    try:
        r = requests.get(
            "https://maps.googleapis.com/maps/api/place/textsearch/json",
            params={
                "query": name,
                "location": f"{lat},{lon}",
                "radius": 3000,
                "type": "lodging",
                "language": "ko",
                "key": GOOGLE_KEY,
            },
            timeout=7,
        )
        r.raise_for_status()
        res = r.json().get("results") or []
        return res[0].get("place_id") if res else None
    except Exception as e:
        logging.warning("TextSearch 실패: %s", e)
        return None

def _details(place_id: str) -> Dict[str, Any]:
    try:
        r = requests.get(
            "https://maps.googleapis.com/maps/api/place/details/json",
            params={
                "place_id": place_id,
                "fields": "price_level,rating,user_ratings_total",
                "language": "ko",
                "key": GOOGLE_KEY,
            },
            timeout=7,
        )
        r.raise_for_status()
        return r.json().get("result") or {}
    except Exception as e:
        logging.warning("Details 실패: %s", e)
        return {}

def enrich_price_level(hotels: List[Dict[str, Any]], center_lat: float, center_lon: float) -> List[Dict[str, Any]]:
    """LiteAPI 가격이 없을 때 Google Places의 price_level(0~4)로 보강"""
    price_level_map = {0:"무료/미정", 1:"₩", 2:"₩₩", 3:"₩₩₩", 4:"₩₩₩₩"}
    out = []
    for h in hotels:
        price = h.get("price")
        lat, lon = h.get("lat"), h.get("lon")
        if price in (None, 0, "0", "0.0"):
            pid = _text_search(h.get("name") or "", float(lat or center_lat), float(lon or center_lon))
            det = _details(pid) if pid else {}
            h["price_level"] = price_level_map.get(det.get("price_level"))
            if det.get("rating"):
                h["rating"] = det["rating"]
        out.append(h)
    return out
