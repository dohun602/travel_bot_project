
import os
import re
import requests
from mongo import load_airport_ennames

iata_to_name = load_airport_ennames()

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

    if "translations" not in result:
        print("❌ DeepL 응답 오류:", result)
        return text

    translated = result["translations"][0]["text"]

    # ✅ 후처리: 'rating'이 잘못 번역되면 교정
    if text.lower() == "rating" and translated in ["정말요", "진짜로"]:
        return "평점"
    return translated


def smart_protect_entities(text):
    tokens = text.split()
    protected = []
    for token in tokens:
        if token[0].isupper() or "-" in token:
            protected.append(f"__{token}__")
        else:
            protected.append(token)
    return " ".join(protected)


def restore_entities(text):
    return re.sub(r"__([A-Za-z\-]+)__", r"\1", text)


def get_airport_koname(iata_code):
    name_en = iata_to_name.get(iata_code)
    if not name_en:
        return iata_code

    name_ko = translate_with_deepl(name_en)
    return f"{name_ko} ({iata_code})"
