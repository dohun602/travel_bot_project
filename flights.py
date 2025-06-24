import os
import requests

AMADEUS_CLIENT_ID = os.getenv("AMADEUS_CLIENT_ID")
AMADEUS_CLIENT_SECRET = os.getenv("AMADEUS_CLIENT_SECRET")


def get_amadeus_token():
    url = "https://test.api.amadeus.com/v1/security/oauth2/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": AMADEUS_CLIENT_ID,
        "client_secret": AMADEUS_CLIENT_SECRET
    }
    response = requests.post(url, data=payload)
    if response.status_code == 200:
        return response.json()["access_token"]
    else:
        print("❌ Amadeus 토큰 요청 실패:", response.text)
        return None


# Amadeus 항공편 검색 함수
def get_flight_info(departure_iata, arrival_iata, departure_date):
    token = get_amadeus_token()
    if not token:
        return None

    url = "https://test.api.amadeus.com/v2/shopping/flight-offers"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "originLocationCode": departure_iata,
        "destinationLocationCode": arrival_iata,
        "departureDate": departure_date,
        "adults": 1,
        "max": 3
    }
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        return response.json().get("data", [])
    else:
        print("❌ 항공편 요청 실패:", response.text)
        return None
