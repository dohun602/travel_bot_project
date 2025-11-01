# -*- coding: utf-8 -*-
"""
LiteAPI 기반 호텔 검색 모듈 (최종 안정판)
- 검색은 'IATA 코드' 또는 '(위도,경도)' 중 하나만 사용 (배타)
- 사용법: from hotels_LITE import search_hotels
"""

from __future__ import annotations
from typing import Optional, Tuple, List, Dict, Any
import os
import logging
import json
import requests

# ──────────────────────────────────────────────────────────────────────────────
# (선택) Mongo 좌표 조회: 프로젝트에 mongo.py가 있다면 재사용
# ──────────────────────────────────────────────────────────────────────────────
try:
    from mongo import get_lat_lon_from_iata  # type: ignore
except Exception:
    def get_lat_lon_from_iata(iata_code: str) -> Optional[Tuple[float, float]]:
        return None

# ──────────────────────────────────────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────────────────────────────────────
LITEAPI_KEY = os.getenv("LITEAPI_KEY")
BASE_URL = "https://api.liteapi.travel/v3.0/data/hotels"

# Mongo 실패 시 좌표 Fallback
IATA_FALLBACK: Dict[str, Tuple[float, float]] = {
    "ICN": (37.4602, 126.4407),
    "GMP": (37.5583, 126.7906),
    "HND": (35.5494, 139.7798),
    "NRT": (35.7730, 140.3929),
    "CTS": (42.7752, 141.6923),
    "KIX": (34.4347, 135.2442),
}

# ──────────────────────────────────────────────────────────────────────────────
# HTTP 세션
# ──────────────────────────────────────────────────────────────────────────────
def _session() -> requests.Session:
    s = requests.Session()
    s.headers.clear()
    s.headers.update({
        "Accept": "application/json",
        "X-Api-Key": LITEAPI_KEY or "",
        "User-Agent": "travel-bot/1.0",
    })
    return s

# ──────────────────────────────────────────────────────────────────────────────
# 정규화
# ──────────────────────────────────────────────────────────────────────────────
def _normalize_hotel(h: Dict[str, Any]) -> Dict[str, Any]:
    """LiteAPI 응답을 통합 포맷으로 정규화"""
    return {
        "hotelId": h.get("id") or h.get("hotelId"),
        "name": h.get("name") or h.get("hotelName"),
        "address": h.get("address") or h.get("formatted_address"),
        "city": h.get("cityName") or h.get("city"),
        "lat": h.get("latitude") if "latitude" in h else h.get("lat"),
        "lon": h.get("longitude") if "longitude" in h else h.get("lon"),
        "distance": h.get("distance") or h.get("dist"),
        "image": h.get("image") or h.get("photoUrl") or h.get("thumbnailUrl") or h.get("photo"),
        "rating": h.get("rating") or h.get("stars") or h.get("reviewScore"),
        "price": h.get("price") or h.get("min_price") or h.get("fromPrice") or h.get("minRate"),
        "currency": h.get("currency") or h.get("priceCurrency") or "USD",
        "amenities": h.get("amenities") or [],
        "raw": h,
    }

# ──────────────────────────────────────────────────────────────────────────────
# 핵심: LiteAPI 호출 (배타 모드 강제)
# ──────────────────────────────────────────────────────────────────────────────
def get_hotels_lite(
    iata_code: Optional[str] = None,
    lat_lon: Optional[Tuple[float, float]] = None,
    radius_m: int = 15000,
    limit: int = 5,
) -> List[Dict]:
    """
    LiteAPI에서 호텔 목록을 조회해 정규화하여 반환.

    검색 모드(배타):
      - 좌표 모드: latitude/longitude (+ radius)
      - IATA 모드: iataCode
    """
    if not LITEAPI_KEY:
        logging.error("❌ LITEAPI_KEY 환경변수가 설정되지 않았습니다.")
        return []

    if radius_m < 1000:
        radius_m = 1000

    lat = lon = None
    if lat_lon and all(lat_lon):
        lat, lon = lat_lon

    # 좌표가 없으면 IATA → Mongo → Fallback
    if (lat is None or lon is None) and iata_code:
        coords = get_lat_lon_from_iata(iata_code)
        if coords:
            lat, lon = coords
        else:
            fb = IATA_FALLBACK.get(iata_code.upper())
            if fb:
                lat, lon = fb

    # 모드 결정(배타)
    use_coord = (lat is not None and lon is not None)
    use_iata  = (iata_code is not None) and not use_coord

    if not use_coord and not use_iata:
        logging.error("❌ get_hotels_lite(): iata_code 또는 (lat, lon) 필요")
        return []

    # 쿼리 파라미터
    if use_coord:
        params: Dict[str, Any] = {
            "apiKey": LITEAPI_KEY,
            "limit": int(limit),
            "radius": int(radius_m),
            "latitude": float(lat),
            "longitude": float(lon),
        }
        masked = {"apiKey": "***", "limit": params["limit"], "radius": params["radius"],
                  "latitude": params["latitude"], "longitude": params["longitude"]}
    else:
        params = {"apiKey": LITEAPI_KEY, "limit": int(limit), "iataCode": iata_code}
        masked = {"apiKey": "***", "limit": params["limit"], "iataCode": iata_code}

    logging.info("[LITE] params (masked) = %r", masked)

    # HTTP
    try:
        with _session() as s:
            r = s.get(BASE_URL, params=params, timeout=12)
    except Exception as e:
        logging.exception(f"❌ LiteAPI 요청 실패: {e}")
        return []

    if r.status_code != 200:
        try:
            body = r.json()
        except Exception:
            body = r.text
        logging.error(f"❌ LiteAPI HTTP {r.status_code}: {body}")
        return []

    try:
        payload = r.json()
    except json.JSONDecodeError:
        logging.error("❌ LiteAPI 응답이 JSON이 아닙니다.")
        return []

    # 응답 형태 가변성 방어
    items: List[Dict[str, Any]]
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        # data가 dict인 케이스, data.hotels가 리스트인 케이스 모두 방어
        if "data" in payload and isinstance(payload["data"], dict):
            items = payload["data"].get("hotels") or payload["data"].get("results") or []
        else:
            items = payload.get("data") or payload.get("hotels") or []
    else:
        items = []

    if not items:
        logging.warning("⚠️ 호텔 결과 없음.")
        return []

    return [_normalize_hotel(h) for h in items[:limit]]

# ──────────────────────────────────────────────────────────────────────────────
# 호환용 래퍼
# ──────────────────────────────────────────────────────────────────────────────
def search_hotels(
    iata_code: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    radius_km: int = 15,
    limit: int = 5,
) -> List[Dict]:
    """
    기존 앱 호환 래퍼:
      - (lat, lon) -> lat_lon
      - radius_km -> radius_m
    """
    lat_lon = (lat, lon) if (lat is not None and lon is not None) else None
    radius_m = max(1000, int(radius_km * 1000))

    if not iata_code and not lat_lon:
        logging.error("❌ search_hotels(): 파라미터 부족 (iata_code 또는 lat/lon 필요)")
        return []

    return get_hotels_lite(
        iata_code=iata_code,
        lat_lon=lat_lon,
        radius_m=radius_m,
        limit=limit,
    )

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    hotels = search_hotels(lat=37.4602, lon=126.4407, radius_km=15, limit=3)
    print("[TEST] 좌표 모드 결과:", len(hotels))
    for h in hotels:
        print(" -", h.get("name"), "|", h.get("price"), h.get("currency"))
