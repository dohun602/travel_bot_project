# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple
import os, math, logging, requests

LOCATIONIQ_KEY = os.getenv("LOCATIONIQ_KEY") or os.getenv("LOCATIONIQ_TOKEN")

def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return round(2 * R * math.asin(math.sqrt(a)), 2)

def _bbox_km(center_lat: float, center_lon: float, radius_km: float = 3.0) -> Tuple[float, float, float, float]:
    # 간단한 근사: 위도 1도≈111km, 경도 1도≈111*cos(lat) km
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(0.1, math.cos(math.radians(center_lat))))
    return (center_lon - dlon, center_lat - dlat, center_lon + dlon, center_lat + dlat)  # (min_lon, min_lat, max_lon, max_lat)

def _search_nearby_by_name(name: str, center_lat: float, center_lon: float) -> Optional[Dict[str, Any]]:
    """
    LocationIQ /v1/search endpoint로 호텔 이름을 중심 좌표 인근에서 검색.
    - 정확도 향상을 위해 작은 viewbox(약 ±3km)로 제한
    - extratags=1, namedetails=1 로 부가정보 확보 시도
    """
    if not LOCATIONIQ_KEY or not name:
        return None

    base = "https://us1.locationiq.com/v1/search.php"
    min_lon, min_lat, max_lon, max_lat = _bbox_km(center_lat, center_lon, radius_km=3.0)
    params = {
        "key": LOCATIONIQ_KEY,
        "q": name,
        "format": "json",
        "limit": 1,
        "normalizecity": 1,
        "namedetails": 1,
        "extratags": 1,
        "viewbox": f"{min_lon},{max_lat},{max_lon},{min_lat}",
        "bounded": 1
    }
    params.update({"accept-language": "ko"})  # ✅ 한국어 주소 요청 추가

    try:
        r = requests.get(base, params=params, timeout=8)
        # 404는 '검색결과 없음'일 수 있으므로 단순히 무시
        if r.status_code == 404:
            return None
        r.raise_for_status()
        arr = r.json()
        return arr[0] if isinstance(arr, list) and arr else None
    except Exception as e:
        logging.info("LocationIQ search 무결과/실패: %s", e)
        return None


def _reverse_geocode(lat: float, lon: float) -> Dict[str, Any]:
    if not LOCATIONIQ_KEY:
        return {}
    url = "https://us1.locationiq.com/v1/reverse.php"
    params = {
        "key": LOCATIONIQ_KEY,
        "lat": lat,
        "lon": lon,
        "format": "json",
        "normalizeaddress": 1,
        "extratags": 1
    }
    params.update({"accept-language": "ko"})

    try:
        r = requests.get(url, params=params, timeout=6)
        r.raise_for_status()
        data = r.json() or {}

        # ✅ 핵심: 문자열 address를 dict 형태로 감싸기
        return {
            "address": {"display_name": data.get("display_name")},  # 딕셔너리로 포장
            "extratags": data.get("extratags", {})
        }

    except Exception as e:
        logging.warning("LocationIQ reverse 실패: %s", e)
        return {}


def _pick_address(obj: Dict[str, Any]) -> Optional[str]:
    if not obj:
        return None
    # priority: display_name -> address.road+... -> None
    if obj.get("display_name"):
        return obj["display_name"]
    addr = obj.get("address") or {}
    parts = [addr.get(k) for k in ["road", "suburb", "city_district", "city", "state", "postcode", "country"] if addr.get(k)]
    return ", ".join(parts) if parts else None

def enrich_with_locationiq(hotels: List[Dict[str, Any]], center_lat: float, center_lon: float) -> List[Dict[str, Any]]:
    """
    LiteAPI 결과(hotels)를 LocationIQ로 보강한다.
    보강 항목:
      - address (정교화), website, phone (가능할 때), distance(보정)
    주의:
      - 가격/별점/사진은 LocationIQ가 제공하지 않으므로 보강 대상 아님
    """
    out = []
    for h in hotels:
        name = (h.get("name") or "").strip()
        lat = h.get("lat")
        lon = h.get("lon")

        # 우선 주소/웹/전화 후보를 이름 기반 검색으로 시도
        det = _search_nearby_by_name(name, float(lat or center_lat), float(lon or center_lon)) if name else None

        # 좌표가 있으면 reverse로 주소 보강
        rev = _reverse_geocode(float(lat), float(lon)) if (lat is not None and lon is not None) else {}

        # 거리 보정
        dist_km = h.get("distance")
        if (dist_km is None) and (lat is not None and lon is not None):
            dist_km = _haversine_km(center_lat, center_lon, float(lat), float(lon))

        # 웹사이트/전화 (OSM extratags에 있을 수도 있음)
        extratags = (det or {}).get("extratags") or {}
        website = extratags.get("website") or extratags.get("contact:website")
        phone = extratags.get("phone") or extratags.get("contact:phone")

        # 최종 주소 선택(검색결과 우선, 없으면 reverse)
        address = _pick_address(det or {}) or _pick_address(rev) or h.get("address")

        out.append({
            **h,
            "address": address,
            "website": website or h.get("website"),
            "phone": phone or h.get("phone"),
            "distance": dist_km,
            # rating/image/price_level은 그대로 유지(또는 None)
        })
    return out
