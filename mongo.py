import pandas as pd
from pymongo import MongoClient


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
