import requests
from datetime import timedelta


def map_weather_code(code):
    code_map = {
        0: "☀️ 맑음",
        1: "🌤️ 대체로 맑음",
        2: "⛅ 구름 조금",
        3: "☁️ 흐림",
        45: "🌫️ 안개",
        48: "🌫️ 짙은 안개",
        51: "🌦️ 가벼운 이슬비",
        53: "🌦️ 이슬비",
        55: "🌧️ 강한 이슬비",
        61: "🌧️ 약한 비",
        63: "🌧️ 비",
        65: "🌧️ 강한 비",
        71: "🌨️ 약한 눈",
        73: "🌨️ 눈",
        75: "❄️ 강한 눈",
        77: "❄️ 싸락눈",
        80: "🌦️ 약한 소나기",
        81: "🌦️ 소나기",
        82: "🌧️ 강한 소나기",
        95: "⛈️ 뇌우",
        96: "⛈️ 뇌우 + 우박",
        99: "⛈️ 강한 뇌우 + 우박"
    }
    return code_map.get(code, "🌈 알 수 없는 날씨")


# 날씨 API - Open-Meteo
def get_weather_forecast(city_name, country_name, start_date, days):
    try:
        location = f"{city_name}, {country_name}"
        location_data = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": location, "format": "json"},
            headers={"User-Agent": "travel-weather-app"}
        ).json()

        if not location_data:
            return None

        lat = location_data[0]["lat"]
        lon = location_data[0]["lon"]

        end_date = start_date + timedelta(days=days - 1)

        weather = requests.get(
            f"https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,weathercode",
                "timezone": "auto",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat()
            }
        ).json()

        results = []
        for i in range(days):
            date = weather['daily']['time'][i]
            max_temp = weather['daily']['temperature_2m_max'][i]
            min_temp = weather['daily']['temperature_2m_min'][i]
            code = weather['daily']['weathercode'][i]
            desc = map_weather_code(code)
            results.append(f"📅 {date}: {desc} / 최고 {max_temp}°C / 최저 {min_temp}°C")

        return "\n".join(results)

    except Exception as e:
        print(f"❌ 날씨 오류: {e}")
        return None