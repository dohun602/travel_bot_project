# translate.py
import os
import re
import requests
from typing import Optional
from mongo import load_airport_ennames

# IATA -> 영문 공항명 매핑 (엑셀/DB에서 로드)
iata_to_name = load_airport_ennames()

# ─────────────────────────────────────────────────────────────
# DeepL 호출 유틸 (이중 시도 + 예외/미번역 방어)
# ─────────────────────────────────────────────────────────────
def translate_with_deepl(text: str,
                         target_lang: str = "KO",
                         source_lang: Optional[str] = None) -> str:
    """
    DeepL 번역:
      1) source_lang(기본 EN)로 시도
      2) 그대로면 자동감지(None)로 재시도
      3) 실패하면 원문 반환
    """
    if not text:
        return text

    api_key = os.getenv("DEEPL_API_KEY")
    if not api_key:
        return text  # 키 없으면 번역 생략

    # free 키면 api-free, 그렇지 않으면 유료 도메인
    url = ("https://api-free.deepl.com/v2/translate"
           if "free" in api_key.lower()
           else "https://api.deepl.com/v2/translate")

    def _call(_src: Optional[str]) -> Optional[str]:
        params = {
            "auth_key": api_key,
            "text": text,
            "target_lang": target_lang.upper(),
        }
        if _src:
            params["source_lang"] = _src.upper()
        try:
            r = requests.post(url, data=params, timeout=10)
            data = r.json()
            if r.status_code != 200 or "translations" not in data:
                return None
            out = (data["translations"][0].get("text") or "").strip()
            return out or None
        except Exception:
            return None

    # 1) EN 가정 → KO
    out = _call(source_lang or "EN")
    # 2) 자동감지 재시도
    if not out or out.strip() == text.strip():
        out = _call(None)
    # 3) 실패 시 원문
    return out if out else text


# ─────────────────────────────────────────────────────────────
# (선택) 엔티티 보호 유틸 - 필요 시 사용 가능
# ─────────────────────────────────────────────────────────────
def smart_protect_entities(text: str) -> str:
    tokens = text.split()
    protected = []
    for tk in tokens:
        if tk and (tk[0].isupper() or "-" in tk):
            protected.append(f"__{tk}__")
        else:
            protected.append(tk)
    return " ".join(protected)

def restore_entities(text: str) -> str:
    return re.sub(r"__([A-Za-z\-]+)__", r"\1", text)


# ─────────────────────────────────────────────────────────────
# DeepL 실패/미번역 시 최소 치환 (유럽권 공항 표현)
# ─────────────────────────────────────────────────────────────
def _fallback_airport_ko(name: str) -> str:
    repl = {
        "Lufthavn": "공항",   # 노르웨이어/덴마크어
        "Flughafen": "공항",  # 독일어
        "Aéroport": "공항",   # 프랑스어
        "Aeropuerto": "공항", # 스페인어
        "Aeroporto": "공항",  # 이탈리아/포르투갈어
        "Airport": "공항",
        " International": " 국제",
        " Intl": " 국제",
    }
    out = name
    for k, v in repl.items():
        out = out.replace(k, v)
    return out


# ─────────────────────────────────────────────────────────────
# IATA -> 한국어 공항명 (이름만 반환, IATA 괄호는 붙이지 않음)
# ─────────────────────────────────────────────────────────────
def get_airport_koname(iata_code: str) -> str:
    """
    IATA 코드를 한국어 공항명으로 변환.
    - 사전(엑셀/DB)에서 영문명 확보
    - DeepL EN→KO 시도, 실패 시 자동감지 재시도
    - 그래도 미번역이면 로컬 치환으로 최소 '○○ 공항' 보장
    """
    if not iata_code:
        return ""

    name_en = iata_to_name.get(iata_code)
    if not name_en:
        return iata_code  # 모르면 코드 그대로

    # DeepL 1차: EN 고정
    name_ko = translate_with_deepl(name_en, target_lang="KO", source_lang="EN")
    # DeepL 2차: 자동감지
    if not name_ko or name_ko.strip() == name_en.strip():
        name_ko = translate_with_deepl(name_en, target_lang="KO")

    # 최종 Fallback
    if not name_ko or name_ko.strip() == name_en.strip():
        name_ko = _fallback_airport_ko(name_en)

    # 특수 케이스 교정 (원하면 추가)
    # 예: 'rating' 잘못 번역 교정처럼 필요 시 여기에 규칙 추가 가능

    return name_ko
