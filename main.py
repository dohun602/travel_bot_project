import os
import json
import streamlit as st
from datetime import datetime, timedelta
from openai import OpenAI
from places_enrich_locationiq import enrich_with_locationiq
from hotels_LITE import search_hotels
from flights import get_flight_info
from translate import get_airport_koname, translate_with_deepl
from iata import location_to_iata
from timezone import load_timezone_mapping, calculate_time_difference_by_iata
from weather import get_weather_forecast
from mongo import load_airport_ennames, get_lat_lon_from_iata, get_airport_name_from_iata
from places_enrich_locationiq import enrich_with_locationiq
from price_enrich_google import enrich_price_level

# ──────────────────────────────────────────────────────────────────────────────
# 초기 로드
# ──────────────────────────────────────────────────────────────────────────────
iata_to_name = load_airport_ennames()
timezone_mapping = load_timezone_mapping()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ──────────────────────────────────────────────────────────────────────────────
# 배경
# ──────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.stApp {
    background-image: url("https://unsplash.com/photos/M0AWNxnLaMw/download?force=true");
    background-size: cover;
    background-position: center;
    background-attachment: fixed;
}
</style>
""", unsafe_allow_html=True)

st.title("🌍 여행지 추천 앱")

# ──────────────────────────────────────────────────────────────────────────────
# 여행지 추천 (LLM)
# ──────────────────────────────────────────────────────────────────────────────
def generate_destination_recommendations(departure_location, departure_date, travel_days, preference, num_recommendations):
    prompt = f"""
    당신은 여행 추천 도우미입니다. 아래 조건에 맞는 여행지를 {num_recommendations}개 추천해주세요.
    각 추천지는 JSON 리스트 형식으로 다음 정보를 포함해주세요:
    - city_en: 도시명 (영문)
    - country_en: 국가명 (영문)
    - city_kr: 도시명 (한글)
    - country_kr: 국가명 (한글)
    - iata_code: 해당 지역의 공항 IATA 코드

    조건:
    출발지: {departure_location}
    출발일: {departure_date}
    여행 기간: {travel_days}일
    사용자 선호: {preference}

    JSON 형식으로만 출력하세요.
    """

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "당신은 여행지를 추천하는 전문가입니다."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )
    try:
        return json.loads(response.choices[0].message.content.strip())
    except json.JSONDecodeError:
        return []

# ──────────────────────────────────────────────────────────────────────────────
# 호텔 카드 렌더링
# ──────────────────────────────────────────────────────────────────────────────
def render_hotels(hotels):
    if not hotels:
        st.write("❌ 호텔 정보를 찾을 수 없습니다.")
        return

    st.write("🏨 **추천 호텔:**")

    # 한글 번역 매핑 (핵심 20개 정도만 미리 정의)
    amenity_map = {
        "Free Wi-Fi": "🌐 무료 Wi-Fi",
        "Wi-Fi": "🌐 Wi-Fi",
        "Parking": "🚗 주차장",
        "Restaurant": "🍽️ 레스토랑",
        "Bar": "🍷 바/라운지",
        "Breakfast Included": "🍳 조식 포함",
        "Air Conditioning": "❄️ 에어컨",
        "Fitness Center": "💪 피트니스 센터",
        "Spa": "💆 스파",
        "Swimming Pool": "🏊 수영장",
        "Laundry Service": "🧺 세탁 서비스",
        "Shuttle Service": "🚌 셔틀 서비스",
        "24-hour Front Desk": "🕛 24시간 프런트",
        "Room Service": "🛎️ 룸서비스",
        "Conference Room": "💼 회의실",
        "Family Rooms": "👨‍👩‍👧‍👦 가족 객실",
        "Wheelchair Accessible": "♿ 장애인 편의시설",
        "Car Rental": "🚙 렌터카 서비스",
        "Pet Friendly": "🐾 반려동물 동반 가능",
        "Non-smoking Rooms": "🚭 금연 객실",
    }

    for h in hotels:
        name = h.get("name") or "(이름 없음)"
        address = h.get("address") or "주소 정보 없음"
        price = h.get("price")
        currency = h.get("currency") or ""
        rating = h.get("rating") or h.get("stars")
        distance = h.get("distance")

        # 🏨 호텔 기본 정보
        st.markdown(f"### 🏨 {name}")
        if price is not None:
            st.markdown(f"- 💵 가격: {price} {currency}")
        else:
            if h.get("price_level"):
                st.markdown(f"- 💵 예상 가격대: {h['price_level']}")
        if rating is not None:
            st.markdown(f"- ⭐ 평점: {rating}")
        if distance is not None:
            st.markdown(f"- 🛫 공항과의 거리: {distance} km")
        st.markdown(f"- 📍 주소: {address}")

        # 🛎️ 편의시설
        if h.get("amenities"):
            amenities = h["amenities"][:8]  # 상위 8개까지만 표시
            translated = [
                amenity_map.get(a, f"• {a}") for a in amenities
            ]
            st.markdown("🛎️ **편의시설:** " + ", ".join(translated))

        # 🖼️ 이미지
        if h.get("image"):
            st.image(h["image"], use_container_width=True)

        st.markdown("---")


# ──────────────────────────────────────────────────────────────────────────────
# UI 입력
# ──────────────────────────────────────────────────────────────────────────────
departure_input = st.text_input("출발지 (도시명)", "서울")
departure_date = st.date_input("출발 날짜", datetime.today())
travel_days = st.number_input("여행 기간 (일)", min_value=1, max_value=30, value=5)
preference = st.text_area("여행지에 바라는 점", "눈이 오는 곳으로 가고 싶어요")

# ──────────────────────────────────────────────────────────────────────────────
# 실행
# ──────────────────────────────────────────────────────────────────────────────
if st.button("✈️ 추천하기"):
    st.info("여행지를 추천받고 있어요...")

    destinations = generate_destination_recommendations(
        departure_location=departure_input,
        departure_date=str(departure_date),
        travel_days=travel_days,
        preference=preference,
        num_recommendations=3
    )

    if not destinations:
        st.error("추천 결과를 불러올 수 없습니다.")
    else:
        for i, dest in enumerate(destinations, 1):
            st.markdown(f"## {i}. {dest['city_kr']} ({dest['city_en']}), {dest['country_kr']}")

            city_en = dest["city_en"]
            country_en = dest["country_en"]

            # 날씨
            weather = get_weather_forecast(city_en, country_en, departure_date, travel_days)
            if weather:
                st.markdown("🌦️ **날씨 예보:**")
                st.markdown(weather.replace("\n", "  \n"))
            else:
                st.write("🌦️ 날씨 정보를 불러올 수 없습니다.")

            # IATA, 좌표
            departure_iata = location_to_iata(departure_input, country_en)
            arrival_iata = dest.get("iata_code") or location_to_iata(city_en, country_en)
            lat, lon = get_lat_lon_from_iata(arrival_iata) if arrival_iata else (None, None)

            # 공항명(영문) 가져오기
            airport_name_en = get_airport_name_from_iata(arrival_iata) or iata_to_name.get(arrival_iata, arrival_iata)

            # DeepL로 한국어 번역 (DeepL API 키는 이미 등록돼 있음)
            try:
                airport_name_en = get_airport_name_from_iata(arrival_iata) or iata_to_name.get(arrival_iata,
                                                                                               arrival_iata)
                # 먼저 get_airport_koname() 시도, 실패하면 DeepL 호출
                airport_name_kr = get_airport_koname(arrival_iata) or translate_with_deepl(airport_name_en,
                                                                                           target_lang="KO",
                                                                                           source_lang="EN")
            except Exception:
                airport_name_kr = airport_name_en  # 실패 시 영문 그대로 표시

            # 출력
            airport_name_en = get_airport_name_from_iata(arrival_iata) or iata_to_name.get(arrival_iata, arrival_iata)
            airport_name_kr = get_airport_koname(arrival_iata) or translate_with_deepl(airport_name_en,target_lang="KO", source_lang="EN")
            st.markdown(f"✈️ **추천 공항: {airport_name_kr} ({arrival_iata})**")

            # 호텔 (LiteAPI)
            hotel_info = []
            try:
                if lat and lon:
                    hotel_info = search_hotels(lat=lat, lon=lon, radius_km=15, limit=3)  # 라이브러리 호출
                elif arrival_iata:
                    hotel_info = search_hotels(iata_code=arrival_iata, limit=3)
            except Exception as e:
                st.warning("호텔 API 호출 중 오류가 발생했습니다.")
                print("호텔 API 에러:", e)

            if hotel_info and lat and lon:
                hotel_info = enrich_with_locationiq(hotel_info, center_lat=lat, center_lon=lon)
                hotel_info = enrich_price_level(hotel_info, center_lat=lat, center_lon=lon)  # ← 추가된 1줄

            render_hotels(hotel_info)

            # 시차 + 항공편
            if departure_iata and arrival_iata:
                diff = calculate_time_difference_by_iata(departure_iata, arrival_iata, timezone_mapping)
                if isinstance(diff, int):
                    if diff == 0:
                        st.write("🕒 현지 시각은 출발지와 동일합니다.")
                    elif diff > 0:
                        st.write(f"🕒 현지 시각은 출발지보다 {diff}시간 빠릅니다.")
                    else:
                        st.write(f"🕒 현지 시각은 출발지보다 {-diff}시간 느립니다.")

                if departure_iata != arrival_iata:
                    flight_info = get_flight_info(departure_iata, arrival_iata, str(departure_date))
                    if flight_info:
                        st.markdown("✈️ **항공편 정보:**")
                        for flight in flight_info:
                            seg = flight["itineraries"][0]["segments"][0]
                            dep, arr = seg["departure"], seg["arrival"]
                            st.write(f"- {dep['iataCode']} → {arr['iataCode']} / {dep['at']} → {arr['at']}")
