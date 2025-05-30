import os
import re
import requests


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


def get_airport_koname(iata_code, iata_to_name):
    name_en = iata_to_name.get(iata_code)
    if not name_en:
        return iata_code
    name_ko = translate_with_deepl(name_en)
    return f"{name_ko} ({iata_code})"
