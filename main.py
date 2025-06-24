import os
import json
import streamlit as st
from datetime import datetime
from dateutil import parser
from openai import OpenAI

from mongo import load_airport_ennames, get_lat_lon_from_iata
from translate import translate_with_deepl, get_airport_koname
from iata import location_to_iata
from timezone import load_timezone_mapping, calculate_time_difference_by_iata
from weather import get_weather_forecast
from hotels import get_hotels_with_places_api
from flights import get_flight_info

# 초기 데이터 로딩
iata_to_name = load_airport_ennames()
timezone_mapping = load_timezone_mapping()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Streamlit 설정
st.set_page_config(layout="wide")
st.markdown(
    """
    <style>
    .stApp {
        background-image: url("https://unsplash.com/photos/M0AWNxnLaMw/download?force=true");
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    }
    </style>
    """,
    unsafe_allow_html=True
)
st.title("✈️ 여행지 추천 봇")

# 여행지 추천 함수
def generate_destination_recommendations(departure_location, departure_date, travel_days, preference, num_recommendations):
    prompt = f"""
    당신은 여행 추천 도우미입니다. 아래 조건에 맞는 여행지를 {num_recommendations}개 추천해주세요.
    각 추천지는 JSON 리스트 형식으로 다음 정보를 포함해주세요:
    - city_en
    - country_en
    - city_kr
    - country_kr
    - iata_code

    조건:
    출발지: {departure_location}
    출발일: {departure_date}
    여행 기간: {travel_days}일
    사용자 선호: {preference}

    반드시 JSON 형식으로만 출력하고 설명은 포함하지 마세요.
    """
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "여행지를 추천하는 전문가입니다."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )
    try:
        return json.loads(response.choices[0].message.content.strip())
    except Exception as e:
        st.error(f"❌ JSON 파싱 오류: {e}")
        return []

# Sidebar 입력
with st.sidebar:
    st.header("여행 조건 입력")
    departure_location = st.text_input("출발 도시", "서울")
    departure_date = st.date_input("출발 날짜", value=datetime.today())
    travel_days = st.slider("여행 기간 (일)", 1, 30, 5)
    preference = st.text_area("여행 선호도", "맛집, 풍경, 바다")
    num_recommendations = st.slider("추천 받을 도시 수", 1, 5, 3)
    submit = st.button("여행지 추천 받기")

# 본문 출력
if submit:
    with st.spinner("추천 중입니다..."):
        destinations = generate_destination_recommendations(
            departure_location, str(departure_date), travel_days, preference, num_recommendations
        )

    for dest in destinations:
        city_en = dest["city_en"]
        country_en = dest["country_en"]
        city_kr = dest["city_kr"]
        country_kr = dest["country_kr"]
        arr_iata = dest["iata_code"]

        st.subheader(f"📍 {city_kr}, {country_kr} ({arr_iata})")

        # 출발지 IATA 찾기
        dep_iata = location_to_iata(departure_location, country_en)

        # 시차
        tz_diff = calculate_time_difference_by_iata(dep_iata, arr_iata, timezone_mapping)
        if tz_diff is not None:
            st.write(f"🕓 시차: {tz_diff:+}시간")

        # 날씨
        st.markdown("☁️ **날씨 예보**")
        weather_info = get_weather_forecast(city_en, country_en, departure_date, travel_days)
        st.code(weather_info if weather_info else "날씨 정보 없음")

        # 항공편
        st.markdown("🛫 **항공편**")
        flights = get_flight_info(dep_iata, arr_iata, str(departure_date))
        if flights:
            for f in flights:
                price = f["price"]["total"]
                segment = f["itineraries"][0]["segments"][0]
                carrier = segment["carrierCode"]
                duration = segment["duration"]
                st.write(f"✈️ {dep_iata} → {arr_iata}, 항공사: {carrier}, 시간: {duration}, 가격: ${price}")
        else:
            st.write("항공편 정보 없음")

        # 호텔
        st.markdown("🏨 **호텔 추천**")
        lat, lon = get_lat_lon_from_iata(arr_iata)
        if lat and lon:
            hotels = get_hotels_with_places_api(lat, lon)
            for h in hotels:
                st.image(h["photo_url"], width=200)
                st.write(f"{h['name']} ⭐ {h['rating']} 📍 {h['address']}")
        else:
            st.write("호텔 정보를 가져올 수 없습니다.")
