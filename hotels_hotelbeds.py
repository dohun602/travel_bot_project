import os
import time
import json
import hashlib
import logging
from typing import List, Dict, Optional, Tuple
import requests

# 환경 변수에서 API 키 불러오기
HB_API_KEY = os.getenv("HOTELBEDS_API_KEY", "").strip()
HB_SECRET = os.getenv("HOTELBEDS_SECRET", "").strip()

# 테스트용 API 엔드포인트
HB_BASE = "https://api.test.hotelbeds.com"
AVAIL_PATH = "/hotel-api/1.0/hotels"  # Availability endpoint

# ---------------------------------------------------------------------
def _signature() -> str:
    """Hotelbeds X-Signature 계산"""
    if not HB_API_KEY or not HB_SECRET:
        raise RuntimeError("환경변수 HOTELBEDS_API_KEY / HOTELBEDS_SECRET 설정 필요")
    ts = str(int(time.time()))
    raw = HB_API_KEY + HB_SECRET + ts
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _headers() -> dict:
    """요청 헤더"""
    return {
        "Api-key": HB_API_KEY,
        "X-Signature": _signature(),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _normalize(hotels: list, limit: int) -> List[Dict]:
    """Hotelbeds 응답을 표준화 (문자열/딕셔너리 혼합 안전 처리)"""
    results: List[Dict] = []

    def _as_str(x, key=None):
        # x가 dict면 key(content 등) 우선, 아니면 str로 변환
        if isinstance(x, dict):
            if key and x.get(key) not in (None, ""):
                return str(x.get(key))
            # dict인데 key가 없으면 가장 그럴듯한 값을 골라보자
            for cand in ("content", "name", "description", "text"):
                if x.get(cand) not in (None, ""):
                    return str(x.get(cand))
            return ""
        return "" if x is None else str(x)

    for h in hotels[: max(1, min(limit, 10))]:
        if not isinstance(h, dict):
            # 혹시 리스트 안에 문자열이 섞여오면 스킵
            continue

        # --- 최저가 뽑기 ---
        min_total, currency = None, None
        rooms = h.get("rooms") or []
        if isinstance(rooms, list):
            for r in rooms:
                rates = (r or {}).get("rates") or []
                if isinstance(rates, list):
                    for rt in rates:
                        price = (rt or {}).get("sellingRate")
                        if price is None:
                            price = (rt or {}).get("net")
                        cur = (rt or {}).get("currency")
                        try:
                            val = float(price) if price is not None else None
                        except Exception:
                            val = None
                        if val is not None and (min_total is None or val < min_total):
                            min_total, currency = val, cur

        # --- 이름/주소/좌표 ---
        raw_name = h.get("name")  # dict 또는 str
        name = _as_str(raw_name, key="content") or _as_str(raw_name)

        addr_obj = h.get("address")  # dict 또는 str
        # address는 보통 dict(content=...), 문자열일 수도 있음
        address = _as_str(addr_obj, key="content")
        dest_name = _as_str(h.get("destinationName"))
        if dest_name and dest_name not in address:
            address = f"{address}, {dest_name}" if address else dest_name

        # 별(카테고리) 표기: 코드/이름 중 있는 것 사용
        stars = h.get("categoryCode") or h.get("categoryName")

        # 좌표
        lat = h.get("latitude")
        lon = h.get("longitude")

        results.append({
            "hotel_id": str(h.get("code") or ""),
            "name": name or "(no name)",
            "stars": stars,
            "price": min_total,
            "currency": currency,
            "address": address or "",
            "lat": lat,
            "lon": lon,
        })

    results.sort(key=lambda x: (x["price"] is None, x["price"] if x["price"] is not None else 0.0))
    return results



def get_hotels_hotelbeds(
    checkin: str,
    checkout: str,
    adults: int = 2,
    limit: int = 5,
    lat_lon: Optional[Tuple[float, float]] = None,
    radius_km: int = 25,
    currency: str = "USD",
    language: str = "ENG",
) -> List[Dict]:
    """좌표 기반 Hotelbeds 호텔 검색"""
    if not lat_lon:
        logging.error("[hotelbeds] lat_lon required")
        return []

    lat, lon = lat_lon
    payload = {
        "stay": {"checkIn": checkin, "checkOut": checkout},
        "occupancies": [{"rooms": 1, "adults": adults, "children": 0}],
        "geolocation": {
            "latitude": lat,
            "longitude": lon,
            "radius": radius_km,
            "unit": "km",
        },
        "filter": {"maxHotels": limit * 3},
        "language": language,
        "currency": currency,
    }

    try:
        url = HB_BASE + AVAIL_PATH
        res = requests.post(url, headers=_headers(), json=payload, timeout=20)
        if res.status_code != 200:
            logging.error(f"[hotelbeds] {res.status_code} {res.text[:300]}")
            return []

        data = res.json()
        hotels = data.get("hotels", {}).get("hotels", [])
        return _normalize(hotels, limit)

    except Exception as e:
        logging.exception(f"[hotelbeds] error: {e}")
        return []
