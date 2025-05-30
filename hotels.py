import os
import requests

API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")


def get_hotels_with_places_api(lat, lon, max_results=3, radius=2000):
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

        if "공항" in name or "Airport" in name:
            continue

        if not rating or not photos:
            continue

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

        if len(hotels) >= max_results:
            break

    return hotels


def get_hotel_offers(lat, lon, max_results=3, radius=2000):
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{lat},{lon}",
        "radius": radius,
        "type": "lodging",
        "key": API_KEY
    }

    response = requests.get(url, params=params)
    if response.status_code != 200:
        print("❌ Google Places API 요청 실패:", response.text)
        return []

    data = response.json().get("results", [])
    hotels = []

    for h in data[:max_results]:
        name = h.get("name", "이름 없음")
        rating = h.get("rating", "평점 없음")
        address = h.get("vicinity", "주소 없음")

        photo_url = None
        if "photos" in h:
            photo_ref = h["photos"][0]["photo_reference"]
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

    return hotels
