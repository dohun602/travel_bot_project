import os
import requests
import streamlit as st
from datetime import datetime, timedelta, timezone
from dateutil import parser
import json
import pytz
import pandas as pd
from openai import OpenAI
from pymongo import MongoClient
from concurrent.futures import ThreadPoolExecutor, as_completed

# API 키 설정
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
AMADEUS_CLIENT_ID = os.getenv("AMADEUS_CLIENT_ID")
AMADEUS_CLIENT_SECRET = os.getenv("AMADEUS_CLIENT_SECRET")
DEEPL_API_KEY = os.getenv("DEEPL_API_KEY") #번역(DeepL)api
API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")



# airports_with_timezone.csv파일에서 해당 이타코드의 공항명(영문)을 가져오는 함수
def load_airport_ennames():
    # MongoDB 연결
    uri = "mongodb+srv://stardohun201:%40ldh258741@cluster0.uldhbqe.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
    client = MongoClient(uri)
    db = client["travel_bot_db"]
    collection = db["airports"]

    # MongoDB에서 문서들 조회
    documents = list(collection.find({}))
    df = pd.DataFrame(documents)

    # 'IATA Code'와 'name' 컬럼으로 변환
    df = df[df["IATA Code"].notnull()]
    return dict(zip(df["IATA Code"], df["Name"]))

iata_to_name = load_airport_ennames()


# 공항 키워드 기반 이름 분리 함수
airport_keywords = ["공항", "Airport", "국제공항", "항공", "Terminal", "터미널"]

def split_airport_from_name(full_name):
    keywords = ["공항", "국제공항", "국제 공항"]
    for keyword in keywords:
        if keyword in full_name:
            idx = full_name.find(keyword) + len(keyword)
            # 앞에 공항 위치, 뒤에 호텔 이름이라 가정
            airport = full_name[:idx].strip()
            hotel = full_name[idx:].strip()
            return hotel, airport
    return full_name, None



# load_airport_ennames에서 반환된 공항명(영문) -> 공항명(한글)로 변경하는 함수
def get_airport_koname(iata_code):
    name_en = iata_to_name.get(iata_code)
    if not name_en:
        return iata_code

    name_ko = translate_with_deepl(name_en)
    return f"{name_ko} ({iata_code})"

# 공항명 번역 함수
def translate_with_deepl(text):
    api_key = os.getenv("DEEPL_API_KEY")
    url = "https://api-free.deepl.com/v2/translate"

    params = {
        "auth_key": api_key,
        "text": text,
        "target_lang": "KO"
    }

    response = requests.post(url, data=params)
    result = response.json()
    translated = result["translations"][0]["text"]

    # ✅ 후처리: 'rating'이 잘못 번역되면 교정
    if text.lower() == "rating" and translated in ["정말요", "진짜로"]:
        return "평점"
    return translated


# 지역명을 IATA 코드로 변환하는 함수
def location_to_iata(location_name: str, destination_country: str = None) -> str:
    if location_name.lower() in ["서울", "seoul"]:
        if destination_country and destination_country.lower() not in ["korea", "south korea", "대한민국", "한국"]:
            return "ICN"
        else:
            return "GMP"

    try:
        if destination_country:
            prompt = (
                f"'{location_name}'에서 출발한다고 가정하고, '{destination_country}'로 해외 여행을 간다고 할 때, "
                f"가장 가까운 국제공항의 IATA 코드를 알려줘. "
                f"절대 도시 코드 (예: SEL, TYO, LON, PAR 등)이나 지역 내 국내공항 (예: RKV, GMP) 말고, "
                f"반드시 실제 국제선 운항이 있는 국제공항 코드 (예: ICN, HND, LHR, KEF 등)만 3글자로 알려줘. "
                f"정확하게 코드만 3글자로만 말해줘. 설명 없이."
            )


        else:
            prompt = (
                f"'{location_name}'에서 출발한다고 가정하고, 국내 여행을 간다고 할 때, "
                f"가장 가까운 국내 공항의 IATA 코드를 알려줘. "
                f"절대 도시 코드 (예: SEL 등) 말고, 실제 공항 코드 (예: GMP, CJU 등)만 3글자로 정확히 알려줘. "
                f"설명 없이 코드만 딱 3글자만 말해줘."
            )

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "당신은 여행 전문가입니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )

        iata_code = response.choices[0].message.content.strip().upper()

        # 도시 코드 방어 필터링
        CITY_CODES = {"SEL", "TYO", "LON", "PAR", "NYC", "CHI", "ROM", "MIL"}
        if iata_code in CITY_CODES:
            raise ValueError(f"❌ 도시 코드 반환됨: {iata_code} → 실제 공항 코드가 필요합니다.")

        INVALID_CODES = {"SEL", "TYO", "LON", "PAR", "NYC", "ROM", "MIL", "RKV", "GMP"}

        if iata_code in INVALID_CODES or len(iata_code) != 3:
            raise ValueError(f"❌ 부적절한 IATA 코드 반환됨: {iata_code}")

        if len(iata_code) == 3:
            return iata_code
        else:
            raise ValueError(f"잘못된 IATA 코드 형식: {iata_code}")



    except Exception as e:
        print(f"❌ ChatGPT를 통해 IATA 코드를 찾는 중 오류 발생: {e}")
        return None

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

# ✅ IATA -> timezone 매핑 로딩 함수 추가
def load_timezone_mapping():
    try:
        # MongoDB 연결
        uri = "mongodb+srv://stardohun201:%40ldh258741@cluster0.uldhbqe.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
        client = MongoClient(uri)
        db = client["travel_bot_db"]
        collection = db["airports"]

        # 문서 전체 조회
        documents = list(collection.find({}))
        df = pd.DataFrame(documents)

        # 필요한 컬럼만 필터링
        df = df[df["IATA Code"].notna() & df["TZ Database Timezone"].notna()]

        # 딕셔너리 생성
        mapping = dict(zip(df["IATA Code"], df["TZ Database Timezone"]))
        return mapping

    except Exception as e:
        print(f"❌ Timezone 매핑 로드 실패: {e}")
        return {}



# ✅ 출발지/도착지 IATA 기준 시차 계산 함수 추가
def calculate_time_difference_by_iata(dep_iata: str, arr_iata: str, timezone_mapping: dict) -> int:
    try:
        tz_name_dep = timezone_mapping.get(dep_iata)
        tz_name_arr = timezone_mapping.get(arr_iata)

        if not tz_name_dep or not tz_name_arr:
            raise ValueError(f"TimeZone 매핑 없음: {dep_iata} or {arr_iata}")

        tz_dep = pytz.timezone(tz_name_dep)
        tz_arr = pytz.timezone(tz_name_arr)

        now_utc = datetime.now(timezone.utc)  # ✅ 타임존 포함된 현재 시간
        now_dep = now_utc.astimezone(tz_dep)
        now_arr = now_utc.astimezone(tz_arr)

        offset_dep = now_dep.utcoffset().total_seconds() / 3600
        offset_arr = now_arr.utcoffset().total_seconds() / 3600

        return int(offset_arr - offset_dep)

    except Exception as e:
        print(f"❌ 시차 계산 실패 ({dep_iata} → {arr_iata}): {e}")
        return None



#
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

        # ❌ 1. 이름에 "공항", "Airport"가 포함되면 제외
        if "공항" in name or "Airport" in name:
            continue

        # ❌ 2. 평점이 없거나 사진이 없으면 제외
        if not rating or not photos:
            continue

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




def get_hotel_offers(lat, lon, max_results=3, radius=2000):
    import os
    import requests

    API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
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

        # 사진 URL 구성
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
#################################

# iata코드를 통해 airports.xlsx에서 위도, 경도를 가져옴
def get_lat_lon_from_iata(iata_code):
    try:
        # MongoDB 연결
        uri = "mongodb+srv://stardohun201:%40ldh258741@cluster0.uldhbqe.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
        client = MongoClient(uri)
        db = client["travel_bot_db"]
        collection = db["airports"]

        # 해당 IATA 코드 문서 찾기
        doc = collection.find_one({"IATA Code": iata_code})

        if doc and "Latitude" in doc and "Longitude" in doc:
            lat = float(doc["Latitude"])
            lon = float(doc["Longitude"])
            return lat, lon
        else:
            print(f"❌ '{iata_code}' 코드에 해당하는 공항을 찾을 수 없습니다.")
            return None, None

    except Exception as e:
        print(f"❌ 위도/경도 조회 실패: {e}")
        return None, None

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


st.markdown(
    """
    <style>
    .stApp {
        background-image: url("https://unsplash.com/photos/M0AWNxnLaMw/download?ixid=M3wxMjA3fDB8MXxhbGx8fHx8fHx8fHwxNzQ2NzU4MjI4fA&force=true");
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    }
    </style>
    """,
    unsafe_allow_html=True
)




# ✅ Streamlit UI 시작 전에 timezone_mapping 로드
st.title("여행 추천 앱")
timezone_mapping = load_timezone_mapping()

# 여행지 추천 함수    문제없음
def generate_destination_recommendations(departure_location, departure_date, travel_days, preference, num_recommendations):
    prompt = f"""
    당신은 여행 추천 도우미입니다. 아래 조건에 맞는 여행지를 {num_recommendations}개 추천해주세요.
    각 추천지는 JSON 리스트 형식으로 다음 정보를 포함해주세요:
    - city_en: 도시명 (영문)
    - country_en: 국가명 (영문)
    - city_kr: 도시명 (한글)
    - country_kr: 국가명 (한글)
    - iata_code: 출발 가능한 공항의 IATA 코드 (예: ICN, NRT)

    조건:
    출발지: {departure_location}
    출발일: {departure_date}
    여행 기간: {travel_days}일
    사용자 선호: {preference}

    JSON 형식으로만 결과를 출력하세요. 다른 설명이나 텍스트는 절대 포함하지 마세요.
    """

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "당신은 여행지를 추천하는 전문가입니다."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )

    content = response.choices[0].message.content.strip()

    try:
        destinations = json.loads(content)
    except json.JSONDecodeError as e:
        print(f"JSON 디코딩 오류: {e}")
        destinations = []

    return destinations


# 시간차 계산 함수
def calculate_time_difference(iata_code):
    try:
        tz_korea = pytz.timezone("Asia/Seoul")
        tz_str = timezone_mapping.get(iata_code)

        if not tz_str:
            print(f"❌ '{iata_code}'에 해당하는 타임존 정보를 찾을 수 없습니다.")
            return None

        tz_destination = pytz.timezone(tz_str)
        now_korea = datetime.now(tz_korea)
        now_dest = datetime.now(tz_destination)

        offset_korea = now_korea.utcoffset().total_seconds() / 3600
        offset_dest = now_dest.utcoffset().total_seconds() / 3600

        difference = offset_dest - offset_korea
        return round(difference)  # 소수점 포함 시 round(), 정수만 원하면 int()

    except Exception as e:
        print(f"❌ 시차 계산 중 오류 발생: {e}")
        return None



# Streamlit UI
st.title("🌍 여행지 추천하기")
st.write("여행 조건을 입력하면 여행지를 추천하고 날씨도 알려드릴게요!")

departure_input = st.text_input("출발지 (지역명)", "서울")
departure_date = st.date_input("출발 날짜", datetime.today())
travel_days = st.number_input("여행 기간 (일)", min_value=1, max_value=30, value=5)
preference = st.text_area("여행지에 바라는 점을 자유롭게 입력하세요", "눈이 오는 곳으로 가고 싶어요")

timezone_mapping = load_timezone_mapping()

if st.button("✈️ 추천하기"):
    # ✅ 추천 버튼 누를 때마다 Streamlit 내부 상태 초기화
    st.session_state.clear()  # 전체 초기화 (원하지 않으면 선택적 초기화도 가능)

    st.info("ChatGPT로부터 여행지를 추천받고 있어요...")

    recommendations = generate_destination_recommendations(
        departure_location=departure_input,
        departure_date=str(departure_date),
        travel_days=travel_days,
        preference=preference,
        num_recommendations=3
    )

    if not recommendations:
        st.error("여행지를 추천받지 못했습니다. 다시 시도해주세요.")
    else:
        st.caption("⏰ 출발·도착 시간은 각각의 공항 현지 시각 기준으로 표시됩니다.")
        for i, dest in enumerate(recommendations, 1):
            with st.container():
                hotel_info = None

                city_kr = dest.get("city_kr", "정보 없음")
                country_kr = dest.get("country_kr", "정보 없음")
                city_en = dest.get("city_en", "")
                country_en = dest.get("country_en", "")

                st.subheader(f"{i}. {city_kr} ({city_en}), {country_kr}")

                weather = get_weather_forecast(city_en, country_en, departure_date, travel_days)
                if weather:
                    st.markdown("🌦️ **날씨 예보:**")
                    st.markdown(weather.replace("\n", "  \n"))
                else:
                    st.write("🌦️ 날씨 정보를 불러올 수 없습니다.")

                departure_iata = location_to_iata(departure_input, country_en)
                arrival_iata = location_to_iata(city_en, country_en)
                print(f"🚀 출발 IATA: {departure_iata}, 도착 IATA: {arrival_iata}")###########################
                print("🧭 추천 목적지 확인:", recommendations)

                # 호텔 정보
                token = get_amadeus_token()
                lat, lon = get_lat_lon_from_iata(arrival_iata)

                print(f"🔎 {arrival_iata}의 위도/경도: {lat}, {lon}")

                if lat and lon:
                    checkin = str(departure_date)
                    checkout = str(departure_date + timedelta(days=travel_days))
                    # Google Places API 기반 호텔 정보 출력
                    hotel_info = get_hotel_offers(lat, lon)

                    if not hotel_info:
                        st.write("❌ 호텔 정보를 찾을 수 없습니다.")
                        print(f"❗ 호텔 정보 없음: {arrival_iata} (lat={lat}, lon={lon})")
                    else:
                        st.write("🏨 추천 호텔:")
                        for hotel in hotel_info:
                            # 사진이 없으면 출력하지 않음
                            if not hotel["photo_url"]:
                                continue

                            # 번역
                            name_en = hotel["name"]
                            name_ko = translate_with_deepl(name_en)
                            hotel_name = f"{name_ko} ({name_en})"

                            address_ko = translate_with_deepl(hotel["address"])
                            address_en = hotel["address"]  # 번역 없이 그대로 사용

                            st.subheader(f"🏨 {hotel_name}")
                            st.markdown(f"⭐ 평점: {hotel['rating']}")
                            st.markdown(f"📍 주소(원문): {address_en}")
                            st.markdown(f"📘 주소(한글): {address_ko}")
                            st.image(hotel["photo_url"], use_container_width=True)
                            st.markdown("---")


                else:
                    st.write("❌ 도착지 공항에서 위도/경도 정보를 찾을 수 없습니다.")

                # 시차 계산 및 출력
                if departure_iata and arrival_iata:
                    time_diff = calculate_time_difference_by_iata(departure_iata, arrival_iata, timezone_mapping)
                    if isinstance(time_diff, int):
                        if time_diff == 0:
                            st.write("🕒 현지 시각은 출발지와 동일합니다.")
                        elif time_diff > 0:
                            st.write(f"🕒 현지 시각은 출발지보다 {time_diff}시간 빠릅니다.")
                        else:
                            st.write(f"🕒 현지 시각은 출발지보다 {-time_diff}시간 느립니다.")
                    else:
                        st.write("🕒 시차 정보를 불러올 수 없습니다.")

                    # 항공편 정보 출력
                    if departure_iata == arrival_iata:
                        st.write("✈ 항공편 정보: 출발지와 도착지가 동일하여 검색하지 않습니다.")
                    else:
                        flight_info = get_flight_info(departure_iata, arrival_iata, str(departure_date))
                        if not flight_info:
                            st.write("✈ 항공편: 정보를 불러올 수 없습니다.")
                        else:
                            st.write("✈ 항공편 정보:")
                            for flight in flight_info:
                                segments = flight["itineraries"][0]["segments"]
                                for seg in segments:
                                    dep = seg["departure"]
                                    arr = seg["arrival"]

                                    dep_display = dep.get("iataCode", "출발지 미확인")
                                    arr_display = arr.get("iataCode", "도착지 미확인")

                                    dep_time = dep.get("at", "출발 시각 없음")
                                    arr_time = arr.get("at", "도착 시각 없음")

                                    dep_time_fmt = parser.parse(dep_time).strftime(
                                        "%Y-%m-%d %H:%M") if dep_time else "출발 시각 없음"
                                    arr_time_fmt = parser.parse(arr_time).strftime(
                                        "%Y-%m-%d %H:%M") if arr_time else "도착 시각 없음"

                                    dep_name = get_airport_koname(dep_display)
                                    arr_name = get_airport_koname(arr_display)

                                    st.write(f"- {dep_name} → {arr_name} / 출발: {dep_time_fmt} / 도착: {arr_time_fmt}")
                else:
                    st.write("✈️ 항공편 정보: 찾을 수 없음.")


