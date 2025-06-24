import os
import requests

API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")


def get_hotels_with_places_api(lat, lon, max_results=3, radius=5000):
    import os
    import requests
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{lat},{lon}",
        "radius": radius,
        "type": "lodging",
        "key": API_KEY
    }

    response = requests.get(url, params=params)
    data = response.json()

    hotels = []

    for h in data.get("results", []):
        name = h.get("name", "")
        rating = h.get("rating")
        address = h.get("vicinity", "주소 없음")
        photos = h.get("photos", [])

        # ❌ 1. 이름에 "공항", "Airport"또는 "Terminal"가 포함되면 제외
        airport_keywords = ["공항", "Airport", "Terminal"]
        if any(keyword in name for keyword in airport_keywords):
            continue

        # ❌ 2. 평점이 없거나 사진이 없으면 제외
        if not rating or not photos:
            continue

        print("총 검색된 호텔 수:", len(data.get("results", [])))
        print("필터 후 남은 호텔 수:", len(hotels))

        # ✅ 사진 URL 생성
        photo_ref = photos[0].get("photo_reference")
        photo_url = (
            f"https://maps.googleapis.com/maps/api/place/photo"
            f"?maxwidth=400&photoreference={photo_ref}&key={API_KEY}"
        )

        hotels.append({
            "name": name,
            "rating": rating,
            "address": address,
            "photo_url": photo_url
        })

        # ✅ 원하는 수량만큼만 가져오기
        if len(hotels) >= max_results:
            break

    return hotels
