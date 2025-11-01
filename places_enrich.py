# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Dict, Any, Optional
import os, math, logging, requests

GOOGLE_KEY = os.getenv("GOOGLE_PLACES_API_KEY") or os.getenv("GOOGLE_API_KEY")

def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    dlat = math.radians(lat2-lat1)
    dlon = math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return round(2 * R * math.asin(math.sqrt(a)), 2)

def _text_search(name: str, lat: float, lon: float) -> Optional[str]:
    if not GOOGLE_KEY or not name:
        return None
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {
        "query": name,
        "location": f"{lat},{lon}",
        "radius": 3000,
        "type": "lodging",
        "language": "ko",
        "key": GOOGLE_KEY,
    }
    try:
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        res = r.json().get("results") or []
        return res[0].get("place_id") if res else None
    except Exception as e:
        logging.warning("Places TextSearch 실패: %s", e)
        return None

def _details(place_id: str) -> Dict[str, Any]:
    if not place_id: return {}
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    fields = ",".join([
        "name","formatted_address","rating","user_ratings_total",
        "price_level","formatted_phone_number","website","url",
        "geometry/location","photos"
    ])
    try:
        r = requests.get(url, params={"place_id": place_id, "fields": fields, "language":"ko", "key": GOOGLE_KEY}, timeout=8)
        r.raise_for_status()
        return r.json().get("result") or {}
    except Exception as e:
        logging.warning("Places Details 실패: %s", e)
        return {}

def _photo_url(photo_ref: str, max_w: int = 800) -> str:
    return f"https://maps.googleapis.com/maps/api/place/photo?maxwidth={max_w}&photoreference={photo_ref}&key={GOOGLE_KEY}"

def enrich_with_places(hotels: List[Dict[str, Any]], center_lat: float, center_lon: float) -> List[Dict[str, Any]]:
    """
    LiteAPI 결과(hotels)를 Google Places 정보로 보강한다.
    반환: 기존 필드 + 다음 필드가 추가/보정됨
      - image, rating, reviews_total, price_level, phone, website, maps_url, address, distance
    """
    price_level_map = {0:"무료/미정", 1:"저가", 2:"중간", 3:"비싸짐", 4:"최상위"}
    out = []
    for h in hotels:
        name = h.get("name") or ""
        lat, lon = h.get("lat"), h.get("lon")

        # place_id 찾기 (이름+좌표 기준)
        pid = _text_search(name, float(lat or center_lat), float(lon or center_lon)) if GOOGLE_KEY else None
        det = _details(pid) if pid else {}

        # 거리 보정(센터 기준)
        dist_km = h.get("distance")
        if (dist_km is None) and (lat is not None and lon is not None):
            dist_km = _haversine_km(center_lat, center_lon, float(lat), float(lon))

        # 이미지 우선순위: LiteAPI → Places photo
        img = h.get("image")
        if not img and det.get("photos"):
            img = _photo_url(det["photos"][0]["photo_reference"])

        out.append({
            **h,
            "image": img,
            "rating": det.get("rating") or h.get("rating"),
            "reviews_total": det.get("user_ratings_total"),
            "price_level": price_level_map.get(det.get("price_level")) if det.get("price_level") is not None else h.get("price_level"),
            "phone": det.get("formatted_phone_number"),
            "website": det.get("website"),
            "maps_url": det.get("url"),
            "address": det.get("formatted_address") or h.get("address"),
            "distance": dist_km,
        })
    return out
