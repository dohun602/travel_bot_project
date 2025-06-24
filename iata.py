import os
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


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
