import os
import json
import streamlit as st
from datetime import datetime, timedelta
from dateutil import parser
from openai import OpenAI
from hotels_hotelbeds import get_hotels_hotelbeds
from hotels_amadeus import get_hotels_amadeus
from flights import get_flight_info
from translate import translate_with_deepl, get_airport_koname
from iata import location_to_iata
from timezone import load_timezone_mapping, calculate_time_difference_by_iata
from weather import get_weather_forecast
from mongo import load_airport_ennames, get_lat_lon_from_iata

# ✅ 초기 로드
iata_to_name = load_airport_ennames()
timezone_mapping = load_timezone_mapping()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ✅ Streamlit 배경
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

# ✅ 여행지 추천 함수
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

# ✅ 호텔 병합 함수
def _merge_hotels(a, b, limit=5):
    seen = set()
    merged = []
    for src in (a + b):
        name = (src.get("name") or "").strip().lower()
        key = (name, round(float(src.get("lat") or 0), 3), round(float(src.get("lon") or 0), 3))
        if name and key not in seen:
            seen.add(key)
            merged.append(src)
    merged.sort(key=lambda x: (x.get("price") is None, float(x.get("price") or 0)))
    return merged[:limit]

# ✅ UI 입력
departure_input = st.text_input("출발지 (도시명)", "서울")
departure_date = st.date_input("출발 날짜", datetime.today())
travel_days = st.number_input("여행 기간 (일)", min_value=1, max_value=30, value=5)
preference = st.text_area("여행지에 바라는 점", "눈이 오는 곳으로 가고 싶어요")

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

            # ✅ 날씨
            weather = get_weather_forecast(city_en, country_en, departure_date, travel_days)
            if weather:
                st.markdown("🌦️ **날씨 예보:**")
                st.markdown(weather.replace("\n", "  \n"))
            else:
                st.write("🌦️ 날씨 정보를 불러올 수 없습니다.")

            # ✅ IATA, 좌표
            departure_iata = location_to_iata(departure_input, country_en)
            arrival_iata = dest.get("iata_code") or location_to_iata(city_en, country_en)
            lat, lon = get_lat_lon_from_iata(arrival_iata) if arrival_iata else (None, None)

            checkin = str(departure_date)
            checkout = str(departure_date + timedelta(days=travel_days))

            # ✅ 호텔: Amadeus + Hotelbeds 하이브리드
            amadeus_list, hotelbeds_list = [], []
            try:
                if lat and lon:
                    amadeus_list = get_hotels_amadeus(
                        checkin=checkin,
                        checkout=checkout,
                        adults=2,
                        limit=3,
                        lat_lon=(lat, lon),
                        city_code=arrival_iata
                    )
                    if not amadeus_list:
                        hotelbeds_list = get_hotels_hotelbeds(
                            checkin=checkin,
                            checkout=checkout,
                            adults=2,
                            limit=3,
                            lat_lon=(lat, lon),
                            radius_km=25
                        )
                else:
                    amadeus_list = get_hotels_amadeus(
                        city_code=arrival_iata,
                        checkin=checkin,
                        checkout=checkout,
                        adults=2,
                        limit=3
                    )

                hotel_info = _merge_hotels(amadeus_list, hotelbeds_list, limit=3)
            except Exception as e:
                st.warning("호텔 API 호출 중 오류가 발생했습니다.")
                print("호텔 API 에러:", e)
                hotel_info = []

            # ✅ 호텔 출력
            if not hotel_info:
                st.write("❌ 호텔 정보를 찾을 수 없습니다.")
            else:
                st.write("🏨 **추천 호텔:**")
                for h in hotel_info:
                    name_en = h.get("name", "Unknown")
                    price = h.get("price")
                    currency = h.get("currency", "KRW")
                    stars = h.get("stars", "N/A")
                    address = h.get("address", "주소 정보 없음")

                    st.markdown(f"**🏨 {name_en}**")
                    st.markdown(f"- ⭐ 성급: {stars}")
                    if price:
                        st.markdown(f"- 💵 가격: {price} {currency}")
                    st.markdown(f"- 📍 주소: {address}")
                    st.markdown("---")

            # ✅ 시차 + 항공편
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
