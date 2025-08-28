import os
import json
import streamlit as st
from datetime import datetime
from datetime import timedelta
from dateutil import parser
from openai import OpenAI
from flights import get_flight_info
from translate import translate_with_deepl, get_airport_koname
from iata import location_to_iata
from timezone import load_timezone_mapping, calculate_time_difference_by_iata
from weather import get_weather_forecast
from hotels import get_hotels_with_hotellook
from mongo import load_airport_ennames
# 초기 데이터 로딩
iata_to_name = load_airport_ennames()
timezone_mapping = load_timezone_mapping()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Streamlit 설정
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

                # 호텔 정보 (HotelLook 전용)
                checkin = str(departure_date)
                checkout = str(departure_date + timedelta(days=travel_days))

                try:
                    hotel_info = get_hotels_with_hotellook(
                        city_en, checkin, checkout, currency="KRW", limit=3
                    )
                except Exception as e:
                    st.warning("호텔 API 응답이 잠시 지연되고 있어요. 다시 시도해 주세요.")
                    print("HotelLook fatal:", e)
                    hotel_info = []

                if not hotel_info:
                    st.write("❌ 호텔 정보를 찾을 수 없습니다.")
                    print(f"❗ 호텔 정보 없음: {city_en} ({checkin} ~ {checkout})")
                else:
                    st.write("🏨 추천 호텔:")
                    for h in hotel_info:
                        name_en = h.get("name") or "(no name)"
                        # 번역은 예외 안전하게
                        try:
                            name_ko = translate_with_deepl(name_en) if name_en and name_en != "(no name)" else name_en
                        except Exception:
                            name_ko = name_en
                        hotel_name = f"{name_ko} ({name_en})" if name_ko and name_ko != name_en else name_en

                        stars = h.get("rating")
                        rating_text = f"{stars}성급" if stars is not None else "등급 정보 없음"

                        price = h.get("price")
                        price_avg = h.get("priceAvg")  # hotels.py에서 priceAvg==price면 None으로 처리해 둠
                        cur = h.get("currency", "KRW")

                        addr = h.get("address") or "주소 정보 없음"
                        try:
                            addr_ko = translate_with_deepl(addr) if addr and addr != "주소 정보 없음" else addr
                        except Exception:
                            addr_ko = addr

                        lat, lon = h.get("lat"), h.get("lon")
                        dist = h.get("distance")

                        st.subheader(f"🏨 {hotel_name}")
                        st.markdown(f"⭐ 등급: {rating_text}")
                        if price is not None:
                            try:
                                st.markdown(f"💵 최저가: {float(price):,.0f} {cur}")
                            except Exception:
                                st.markdown(f"💵 최저가: {price} {cur}")
                        if price_avg is not None:  # 평균가가 유효할 때만 노출
                            try:
                                st.markdown(f"🧮 평균가: {float(price_avg):,.0f} {cur}")
                            except Exception:
                                st.markdown(f"🧮 평균가: {price_avg} {cur}")

                        st.markdown(f"📍 주소(원문): {addr}")
                        if addr_ko != addr:
                            st.markdown(f"📘 주소(한글): {addr_ko}")
                        if lat is not None and lon is not None:
                            st.caption(f"🧭호텔 좌표: 위도:{lat}, 경도:{lon}")
                        if dist is not None:
                            st.caption(f"📏 중심지까지 거리(추정): {dist} km")
                        st.markdown("---")

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