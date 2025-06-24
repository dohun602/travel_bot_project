import pytz
from datetime import datetime, timezone
from pymongo import MongoClient
import pandas as pd


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
