import streamlit as st
from datetime import datetime, timedelta
from dateutil import parser

from mongo import load_airport_ennames, get_lat_lon_from_iata
from translate import translate_with_deepl, get_airport_koname
from iata import location_to_iata
from timezone import load_timezone_mapping, calculate_time_difference_by_iata
from weather import get_weather_forecast
from hotels import get_hotel_offers
from flights import get_flight_info

# 데이터 로딩
iata_to_name = load_airport_ennames()
timezone_mapping = load_timezone_mapping()

# UI
st.markdown("""
<style>
.stApp {
    background-image: url("https://unsplash.com/photos/M0AWNxnLaMw/download?ixid=M3wxMjA3fDB8MXxhbGx8fHx8fHx8fHwxNzQ2NzU4MjI4fA&force=true");
    background-size: cover;
    background-position: center;
    background-attachment: fixed;
}
</style>
""", unsafe_allow_html=True)

st.title("🌍 여행지 추천하기")
st.write("여행 조건을 입력하면 여행지를 추천하고 날씨도 알려드릴게요!")

# 사용자 입력
departure_input = st.text_input("출발지 (지역명)", "서울")
departure_date = st.date_input("출발 날짜", datetime.today())
travel_days = st.number_input("여행 기간 (일)", min_value=1, max_value=30, value=5)
preference = st.text_area("여행지에 바라는 점을 자유롭게 입력하세요", "눈이 오는 곳으로 가고 싶어요")

# 여행지 추천 함수
from openai import OpenAI
import os
import json
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generate_destination_recommendations(departure_location, departure_date, travel_days, preference, num_recommendations):
    prompt = f"""
    당신은 여행 추천 도우미입니다. 아래 조건에 맞는 여행지를 {num_recommendations}개 추천해주세요.
    각 추천지는 JSON 리스트 형식으로 다음 정보를 포함해주세요:
    - city_en: 도시명 (영문)
    - country_en: 국가명 (영문)
    - city_kr: 도시명 (한글)
    - country_kr: 국가명 (한글)
    - iata_code: 출발 가능한 공항의 IATA 코드

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

if st.button("✈️ 추천하기"):
    st.session_state.clear()
    st.info("ChatGPT로부터 여행지를 추천받고 있어요...")

    recommendations = generate_destination_recommendations(
        departure_input, str(departure_date), travel_days, preference, 3
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

                # 날씨 출력
                weather = get_weather_forecast(city_en, country_en, departure_date, travel_days)
                if weather:
                    st.markdown("🌦️ **날씨 예보:**")
                    st.markdown(weather.replace("\n", "  \n"))
                else:
                    st.write("🌦️ 날씨 정보를 불러올 수 없습니다.")

                # IATA 코드
                departure_iata = location_to_iata(departure_input, country_en)
                arrival_iata = location_to_iata(city_en, country_en)

                lat, lon = get_lat_lon_from_iata(arrival_iata)
                if lat and lon:
                    hotel_info = get_hotel_offers(lat, lon)
                    if hotel_info:
                        st.write("🏨 추천 호텔:")
                        for hotel in hotel_info:
                            if not hotel["photo_url"]:
                                continue

                            name_en = hotel["name"]
                            name_ko = translate_with_deepl(name_en)
                            hotel_name = f"{name_ko} ({name_en})"
                            address_ko = translate_with_deepl(hotel["address"])
                            address_en = hotel["address"]

                            st.subheader(f"🏨 {hotel_name}")
                            st.markdown(f"⭐ 평점: {hotel['rating']}")
                            st.markdown(f"📍 주소(원문): {address_en}")
                            st.markdown(f"📘 주소(한글): {address_ko}")
                            st.image(hotel["photo_url"], use_container_width=True)
                            st.markdown("---")
                    else:
                        st.write("❌ 호텔 정보를 찾을 수 없습니다.")
                else:
                    st.write("❌ 도착지 공항의 위치를 찾을 수 없습니다.")

                # 시차 출력
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
                if departure_iata and arrival_iata and departure_iata != arrival_iata:
                    flight_info = get_flight_info(departure_iata, arrival_iata, str(departure_date))
                    if flight_info:
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

                                dep_time_fmt = parser.parse(dep_time).strftime("%Y-%m-%d %H:%M") if dep_time else "출발 시각 없음"
                                arr_time_fmt = parser.parse(arr_time).strftime("%Y-%m-%d %H:%M") if arr_time else "도착 시각 없음"

                                dep_name = get_airport_koname(dep_display, iata_to_name)
                                arr_name = get_airport_koname(arr_display, iata_to_name)

                                st.write(f"- {dep_name} → {arr_name} / 출발: {dep_time_fmt} / 도착: {arr_time_fmt}")
                    else:
                        st.write("✈ 항공편: 정보를 불러올 수 없습니다.")
                else:
                    st.write("✈ 항공편 정보: 찾을 수 없음.")
