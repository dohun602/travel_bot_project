# hotels_amadeus.py
import os, time, logging, requests
from typing import List, Dict, Optional, Tuple

AMADEUS_CLIENT_ID = os.getenv("AMADEUS_CLIENT_ID", "").strip()
AMADEUS_CLIENT_SECRET = os.getenv("AMADEUS_CLIENT_SECRET", "").strip()

_AMADEUS_TOKEN = None
_AMADEUS_TOKEN_EXP = 0

def _oauth_token() -> str:
    global _AMADEUS_TOKEN, _AMADEUS_TOKEN_EXP
    if _AMADEUS_TOKEN and time.time() < _AMADEUS_TOKEN_EXP - 60:
        return _AMADEUS_TOKEN
    if not AMADEUS_CLIENT_ID or not AMADEUS_CLIENT_SECRET:
        raise RuntimeError("Amadeus API 키가 없습니다. AMADEUS_CLIENT_ID/SECRET 환경변수를 설정하세요.")
    r = requests.post(
        "https://test.api.amadeus.com/v1/security/oauth2/token",
        data={"grant_type":"client_credentials","client_id":AMADEUS_CLIENT_ID,"client_secret":AMADEUS_CLIENT_SECRET},
        timeout=10
    )
    r.raise_for_status()
    data = r.json()
    _AMADEUS_TOKEN = data["access_token"]
    _AMADEUS_TOKEN_EXP = time.time() + int(data.get("expires_in", 1800))
    return _AMADEUS_TOKEN

def _get(url: str, params: dict) -> dict:
    token = _oauth_token()
    h = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=h, params=params, timeout=15)
    if r.status_code != 200:
        logging.error(f"[amadeus REST] {r.status_code} {r.text[:200]}")
        return {}
    return r.json() or {}

def _hotels_by_geocode(lat: float, lon: float, radius_km: int) -> List[str]:
    """v1 by-geocode → hotelIds 리스트 반환"""
    js = _get(
        "https://test.api.amadeus.com/v1/reference-data/locations/hotels/by-geocode",
        {"latitude": lat, "longitude": lon, "radius": radius_km, "radiusUnit": "KM"}
    )
    ids = []
    for it in js.get("data", []) or []:
        hid = it.get("hotelId") or it.get("id")
        if hid:
            ids.append(hid)
    return ids

def _hotels_by_city(city_code: str) -> List[str]:
    """v1 by-city → hotelIds 리스트 반환"""
    js = _get(
        "https://test.api.amadeus.com/v1/reference-data/locations/hotels/by-city",
        {"cityCode": city_code}
    )
    ids = []
    for it in js.get("data", []) or []:
        hid = it.get("hotelId") or it.get("id")
        if hid:
            ids.append(hid)
    return ids

def _offers_by_hotel_ids(hotel_ids: List[str], checkin: str, checkout: str, adults: int) -> list:
    """v3 shopping hotel-offers (hotelIds 필수)"""
    if not hotel_ids:
        return []
    js = _get(
        "https://test.api.amadeus.com/v3/shopping/hotel-offers",
        {
            "hotelIds": ",".join(hotel_ids[:100]),  # 안전상 100개 제한
            "checkInDate": checkin,
            "checkOutDate": checkout,
            "adults": adults,
        }
    )
    return js.get("data", []) or []

def _normalize_items(items: list, limit: int) -> List[Dict]:
    out: List[Dict] = []
    for it in items[: max(1, min(limit, 10))]:
        hotel = it.get("hotel") or {}
        offers = it.get("offers") or []
        offer0 = offers[0] if offers else {}
        price = (offer0.get("price") or {}).get("total")
        currency = (offer0.get("price") or {}).get("currency")
        addr = hotel.get("address") or {}
        lines = addr.get("lines") or []
        address = ", ".join(lines) if lines else addr.get("cityName")

        out.append({
            "hotel_id": hotel.get("hotelId") or hotel.get("id"),
            "name": hotel.get("name"),
            "chain": hotel.get("chainCode"),
            "stars": hotel.get("rating"),
            "price": price,
            "currency": currency,
            "address": address,
            "lat": hotel.get("latitude"),
            "lon": hotel.get("longitude"),
        })
    out.sort(key=lambda x: (x["price"] is None, float(x["price"]) if x["price"] else 0.0))
    return out

def get_hotels_amadeus(
    city_code: Optional[str] = None,
    checkin: str = "",
    checkout: str = "",
    adults: int = 2,
    limit: int = 5,
    lat_lon: Optional[Tuple[float, float]] = None,
    radius_km: int = 25,   # 반경 기본 25km로 확대
) -> List[Dict]:
    """
    1) 좌표가 있으면 by-geocode로 호텔ID들 수집
    2) 없으면 by-city로 호텔ID 수집
    3) 수집한 ID로 v3 hotel-offers 호출
    """
    try:
        hotel_ids: List[str] = []
        if lat_lon:
            lat, lon = lat_lon
            hotel_ids = _hotels_by_geocode(lat, lon, radius_km)
        elif city_code:
            hotel_ids = _hotels_by_city(city_code)
        else:
            logging.error("[amadeus] city_code나 lat_lon 중 하나는 필요합니다.")
            return []

        if not hotel_ids:
            return []  # 진짜로 주변에 호텔 레퍼런스가 없는 경우

        items = _offers_by_hotel_ids(hotel_ids, checkin, checkout, adults)
        return _normalize_items(items, limit)

    except Exception as e:
        logging.exception(f"[amadeus] 예외: {e}")
        return []
