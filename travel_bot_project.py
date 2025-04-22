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
    return result["translations"][0]["text"]

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
                f"가장 가까운 국제공항의 IATA 코드를 알려줘. 반드시 국제선 운항 공항이어야 해. 코드만 딱 3글자로 알려줘."
            )
        else:
            prompt = (
                f"'{location_name}'에서 출발한다고 가정하고, 국내 여행을 간다고 할 때, "
                f"가장 가까운 국내 공항의 IATA 코드를 알려줘. 반드시 국내 공항이어야 해. 코드만 딱 3글자로 알려줘."
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
        if len(iata_code) == 3:
            return iata_code
        else:
            raise ValueError(f"잘못된 IATA 코드 형식: {iata_code}")

    except Exception as e:
        print(f"❌ ChatGPT를 통해 IATA 코드를 찾는 중 오류 발생: {e}")
        return None

# Amadeus API 인증 토큰(access token)을 발급받는 함수
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
from datetime import datetime

def calculate_time_difference_by_iata(dep_iata: str, arr_iata: str, timezone_mapping: dict) -> int:
    try:
        tz_name_dep = timezone_mapping.get(dep_iata)
        tz_name_arr = timezone_mapping.get(arr_iata)

        if not tz_name_dep or not tz_name_arr:
            raise ValueError(f"TimeZone 매핑 없음: {dep_iata} or {arr_iata}")

        tz_dep = pytz.timezone(tz_name_dep)
        tz_arr = pytz.timezone(tz_name_arr)

        now_naive = datetime.utcnow()
        now_dep = tz_dep.localize(now_naive)
        now_arr = tz_arr.localize(now_naive)

        offset_dep = now_dep.utcoffset().total_seconds() / 3600
        offset_arr = now_arr.utcoffset().total_seconds() / 3600

        return int(offset_arr - offset_dep)

    except Exception as e:
        print(f"❌ 시차 계산 실패 ({dep_iata} → {arr_iata}): {e}")
        return None



# 위도, 경도를 기준으로 Amadeus API를 통해 호텔 가격 정보를 조회하는 함수
def get_hotels_with_price(lat, lon, checkin, checkout, adults=1):
    from amadeus import Client, ResponseError

    amadeus = Client(
        client_id=os.getenv("AMADEUS_CLIENT_ID"),
        client_secret=os.getenv("AMADEUS_CLIENT_SECRET")
    )

    try:
        geo_response = amadeus.reference_data.locations.hotels.by_geocode.get(
            latitude=lat,
            longitude=lon,
            radius=20,
            radiusUnit='KM'
        )

        hotel_ids = [h['hotelId'] for h in geo_response.data]

        results = []
        for hid in hotel_ids:
            try:
                offer = amadeus.shopping.hotel_offers_search.get(
                    hotelIds=hid,
                    checkInDate=checkin,
                    checkOutDate=checkout,
                    adults=adults
                )

                hotel_data = offer.data[0]
                name = hotel_data['hotel']['name']
                price = hotel_data['offers'][0]['price']['total']
                results.append((name, price))

                if len(results) >= 3:
                    break
            except ResponseError:
                continue

        return results

    except ResponseError as e:
        print("❌ Amadeus API Error:", e)
        return []



def get_hotel_offers(hotel_ids, checkin_date, checkout_date, token):
    url = "https://test.api.amadeus.com/v3/shopping/hotel-offers"
    headers = {"Authorization": f"Bearer {token}"}
    valid_hotels = []

    def fetch_offer(hid):
        params = {
            "hotelIds": hid,
            "checkInDate": checkin_date,
            "checkOutDate": checkout_date,
            "adults": 1,
            "roomQuantity": 1,
            "currency": "KRW"
        }
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            if res.status_code == 200:
                data = res.json().get("data", [])
                if data:
                    hotel = data[0]
                    name = hotel.get("hotel", {}).get("name", "이름 없음")
                    price = hotel["offers"][0]["price"].get("total", "가격 정보 없음")
                    return (name, f"{price} KRW")
        except:
            return None

    # 병렬 요청 처리 (최대 5개 동시에, 10개까지 시도)
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(fetch_offer, hid) for hid in hotel_ids[:20]]
        for future in as_completed(futures):
            result = future.result()
            if result:
                valid_hotels.append(result)
            if len(valid_hotels) >= 3:
                break

    return valid_hotels

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


# 날씨 API - Open-Meteo          문제없음
def get_weather_forecast(city_name, country_name):
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

        weather = requests.get(
            f"https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,weathercode",
                "timezone": "auto"
            }
        ).json()

        max_temp = weather['daily']['temperature_2m_max'][0]
        min_temp = weather['daily']['temperature_2m_min'][0]
        weather_code = weather['daily']['weathercode'][0]
        weather_description = map_weather_code(weather_code)

        return f"{weather_description} / 최고 {max_temp}°C / 최저 {min_temp}°C"
    except Exception as e:
        print(f"❌ 날씨 오류: {e}")
        return None

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

                city_kr = dest.get("city_kr", "정보 없음")
                country_kr = dest.get("country_kr", "정보 없음")
                city_en = dest.get("city_en", "")
                country_en = dest.get("country_en", "")

                st.subheader(f"{i}. {city_kr} ({city_en}), {country_kr}")

                weather = get_weather_forecast(city_en, country_en)
                st.write(f"🌦️ 날씨: {weather if weather else '정보 없음'}")

                departure_iata = location_to_iata(departure_input, country_en)
                arrival_iata = location_to_iata(city_en, country_en)

                # 호텔 정보
                token = get_amadeus_token()
                lat, lon = get_lat_lon_from_iata(arrival_iata)

                if lat and lon:
                    checkin = str(departure_date)
                    checkout = str(departure_date + timedelta(days=travel_days))
                    hotel_info = get_hotels_with_price(lat, lon, checkin, checkout)

                    if hotel_info:
                        st.write("🏨 추천 호텔:")
                        hotel_lines = [f"{name} - 💰 {price}" for name, price in hotel_info]
                        st.markdown("\n".join([f"- {line}" for line in hotel_lines]))
                    else:
                        st.write("❌ 호텔 정보를 찾을 수 없습니다.")
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


