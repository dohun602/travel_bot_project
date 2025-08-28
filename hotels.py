# hotels.py (완전 교체본: HotelLook + LocationIQ 주소 보강)
import os
import time
import requests
from functools import lru_cache
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ─────────────────────────────────────────────────────────
# ENV
HOTELLOOK_TOKEN = os.getenv("HOTELLOOK_API_TOKEN")
LOCATIONIQ_KEY  = os.getenv("LOCATIONIQ_KEY")   # pk.****** (us1 기준)
LI_BASE         = os.getenv("LOCATIONIQ_BASE", "https://us1.locationiq.com")  # eu 계정이면 eu1로

# ─────────────────────────────────────────────────────────
# 공통 HTTP 세션(재시도/백오프/UA)
def _make_session():
    s = requests.Session()
    retry = Retry(
        total=4,                 # 최대 재시도
        connect=2,               # 연결 단계 재시도
        read=2,                  # 읽기 단계 재시도
        backoff_factor=0.8,      # 0.8s → 1.6s → 2.4s …
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods={"GET"},
        raise_on_status=False,
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update({"User-Agent": "travelbot/1.0"})
    return s

HTTP = _make_session()

def _http_get(url: str, params: dict, timeout=(5, 30)):
    """세션/재시도/타임아웃 + 상태 체크"""
    r = HTTP.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r

# ─────────────────────────────────────────────────────────
# HotelLook: 도시명 → locationId
def _lookup_location_id(city_en: str) -> str | None:
    try:
        r = _http_get(
            "https://engine.hotellook.com/api/v2/lookup.json",
            params={"query": city_en, "lang": "en", "lookFor": "both", "limit": 3},
            timeout=(5, 20),
        )
        j = r.json()
        locs = (j.get("results", {}).get("locations") or [])
        return str(locs[0]["id"]) if locs else None
    except requests.exceptions.RequestException as e:
        print(f"❌ lookup 실패: {e}")
        return None

# ─────────────────────────────────────────────────────────
# LocationIQ: 역/정방향 지오코딩 (1순위)
@lru_cache(maxsize=4096)
def _li_reverse(lat: float, lon: float) -> str | None:
    if not LOCATIONIQ_KEY:
        return None
    try:
        r = requests.get(
            f"{LI_BASE}/v1/reverse",
            params={"key": LOCATIONIQ_KEY, "lat": lat, "lon": lon, "format": "json"},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json().get("display_name")
    except Exception:
        pass
    return None

@lru_cache(maxsize=4096)
def _li_geocode(q: str):
    """'호텔명, 도시명' → (lat, lon, display_name)"""
    if not LOCATIONIQ_KEY:
        return None
    try:
        r = requests.get(
            f"{LI_BASE}/v1/search",
            params={"key": LOCATIONIQ_KEY, "q": q, "format": "json", "limit": 1},
            timeout=10,
        )
        if r.status_code == 200:
            arr = r.json()
            if arr:
                obj = arr[0]
                return float(obj["lat"]), float(obj["lon"]), obj.get("display_name")
    except Exception:
        pass
    return None

# ─────────────────────────────────────────────────────────
# Nominatim(공용) 폴백
@lru_cache(maxsize=2048)
def _reverse_geocode(lat: float, lon: float) -> str | None:
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"format": "json", "lat": lat, "lon": lon, "zoom": 16, "addressdetails": 1},
            headers={"User-Agent": "travelbot/1.0 (contact: you@example.com)"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("display_name")
    except Exception:
        pass
    return None

@lru_cache(maxsize=2048)
def _geocode_by_name_city(q: str):
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"format": "json", "q": q, "limit": 1, "addressdetails": 1},
            headers={"User-Agent": "travelbot/1.0 (contact: you@example.com)"},
            timeout=10,
        )
        if resp.status_code == 200:
            arr = resp.json()
            if arr:
                obj = arr[0]
                return float(obj["lat"]), float(obj["lon"]), obj.get("display_name")
    except Exception:
        pass
    return None

# ─────────────────────────────────────────────────────────
# 메인: 호텔 목록/가격은 HotelLook, 주소는 LocationIQ로 보강
def get_hotels_with_hotellook(city_en: str, checkin: str, checkout: str,
                              currency: str = "KRW", limit: int = 3):
    if not HOTELLOOK_TOKEN:
        print("❌ HOTELLOOK_API_TOKEN 환경변수가 없습니다.")
        return []

    loc_id = _lookup_location_id(city_en)
    if not loc_id:
        print(f"❌ '{city_en}' locationId를 찾지 못했습니다.")
        return []

    params = {
        "locationId": loc_id,
        "checkIn": checkin,
        "checkOut": checkout,
        "currency": currency,
        "limit": limit,
        "token": HOTELLOOK_TOKEN,
    }

    # 1차 시도
    try:
        r = _http_get("https://engine.hotellook.com/api/v2/cache.json",
                      params=params, timeout=(5, 30))
    except requests.exceptions.ReadTimeout:
        # 2차 시도: 더 긴 타임아웃 + limit 축소
        print("⏳ cache 타임아웃 → 재시도(긴 타임아웃, limit 축소)")
        params_retry = dict(params, limit=max(1, min(2, limit)))
        try:
            r = _http_get("https://engine.hotellook.com/api/v2/cache.json",
                          params=params_retry, timeout=(5, 45))
        except requests.exceptions.RequestException as e:
            print(f"❌ HotelLook 재시도 실패: {e}")
            return []
    except requests.exceptions.RequestException as e:
        print(f"❌ HotelLook 요청 실패: {e}")
        return []

    hotels_raw = r.json() or []
    out = []

    for h in hotels_raw:
        name  = h.get("hotelName") or h.get("name") or "(no name)"
        stars = h.get("stars")
        p_min = h.get("priceFrom")
        p_avg = h.get("priceAvg")
        if (p_avg is None) or (p_min is not None and p_avg == p_min):
            p_avg = None  # 평균가가 의미 없으면 숨김

        addr = h.get("address") or h.get("city")
        loc  = h.get("location") or {}
        lat, lon = loc.get("lat"), loc.get("lon")
        dist = h.get("distance")
        hotel_id = h.get("hotelId") or h.get("id")

        # 주소 폴백: LocationIQ 1순위 → 실패 시 Nominatim
        if not addr:
            if lat is not None and lon is not None:
                addr = _li_reverse(lat, lon) or _reverse_geocode(lat, lon)
                time.sleep(0.5)  # LocationIQ Free: 2 rps 권장
            else:
                q = f"{name}, {city_en}"
                geo = _li_geocode(q) or _geocode_by_name_city(q)
                if geo:
                    lat, lon, disp = geo
                    addr = disp
                    time.sleep(0.5)

        out.append({
            "name": name,
            "rating": stars,               # 성급(정수)
            "address": addr or "주소 정보 없음",
            "price": p_min,
            "priceAvg": p_avg,
            "currency": currency,
            "distance": dist,
            "hotelId": hotel_id,
            "lat": lat,
            "lon": lon,
            "photo_url": None,            # Hotellook cache엔 사진 거의 없음
        })

    return out
