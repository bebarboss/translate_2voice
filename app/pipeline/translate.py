"""แปลบทเป็นภาษาปลายทาง (ไทยหรืออังกฤษ) ด้วย Typhoon และย่อบทให้พอดีเวลา

เส้นทางการแปล
- ต้นฉบับเป็นภาษาเดียวกับปลายทาง        → ไม่แปล แต่ให้ Typhoon แก้คำที่ถอดเสียงผิด (ไม่มี API key ใช้บทเดิม)
- อังกฤษ → ไทย + TRANSLATE_EN_LOCAL=true  → Typhoon Translate บนเครื่อง
- ที่เหลือทั้งหมด                          → Typhoon 2.5 ผ่าน API (OpenAI-compatible)
"""
import json
import logging
import re
import time
import unicodedata
from typing import Callable, Optional

from ..config import settings
from ..schemas import Utterance
from .transcribe import SENTENCE_END

log = logging.getLogger("dubbing.translate")

LANG_NAMES = {
    "zh": "จีน", "yue": "จีนกวางตุ้ง", "en": "อังกฤษ", "ko": "เกาหลี", "ja": "ญี่ปุ่น",
    "vi": "เวียดนาม", "id": "อินโดนีเซีย", "ms": "มาเลย์", "tl": "ฟิลิปปินส์", "hi": "ฮินดี",
    "es": "สเปน", "fr": "ฝรั่งเศส", "de": "เยอรมัน", "ru": "รัสเซีย", "pt": "โปรตุเกส",
    "lo": "ลาว", "km": "เขมร", "my": "พม่า", "th": "ไทย",
}
LANG_NAMES_EN = {
    "zh": "Chinese", "yue": "Cantonese", "en": "English", "ko": "Korean", "ja": "Japanese",
    "vi": "Vietnamese", "id": "Indonesian", "ms": "Malay", "tl": "Filipino", "hi": "Hindi",
    "es": "Spanish", "fr": "French", "de": "German", "ru": "Russian", "pt": "Portuguese",
    "lo": "Lao", "km": "Khmer", "my": "Burmese", "th": "Thai",
}

SYSTEM_PROMPT_TH = """คุณคือนักแปลบทพากย์ละครมืออาชีพ แปลบทพูดเป็นภาษาไทยสำหรับให้นักพากย์อ่าน
กฎ:
1. แปลให้ตรงความหมาย: ทุกท่อนต้องมีใจความครบตามต้นฉบับ ห้ามเติมเนื้อหาที่ต้นฉบับไม่ได้พูด ห้ามตีความเกินหรือเปลี่ยนเรื่อง
   ชื่อ ตัวเลข เวลา สถานที่ คำปฏิเสธ (ไม่/อย่า/ยัง) และคำถามต้องตรงกับต้นฉบับเสมอ
2. แปลเป็นคำพูด ไม่ใช่ภาษาเขียน: เขียนแบบที่คนไทยพูดกันจริงในสถานการณ์นั้น ให้นักพากย์อ่านออกเสียงแล้วลื่นปาก
   ไม่แปลทีละคำ เรียงประโยคแบบไทย ใช้คำลงท้ายและคำอุทานตามธรรมชาติ (นะ สิ เถอะ ล่ะ หรอก เหรอ โอ๊ย เฮ้ย)
   เลี่ยงคำภาษาเขียนหรือภาษาทางการ เช่น ซึ่ง ดังนั้น อย่างไรก็ตาม กระผม ดิฉัน ท่าน(เมื่อไม่ใช่ยศ) ทำการ มีความ… เว้นแต่ตัวละครพูดแบบนั้นจริง
   ประโยคต้องเต็มแบบที่คนพูด ไม่ห้วนเป็นวลีโทรเลข และห้ามใช้คำย่อหรือตัวย่อ (ชม. กม. กก. รพ. กทม. ฯลฯ) ให้เขียนเต็มตามที่อ่านออกเสียง เช่น "สองชั่วโมง" เพราะนักพากย์อ่านตามตัวอักษร
   ตัวอย่าง: "I don't think that's a good idea." → "ฉันว่าไม่ดีมั้ง" ไม่ใช่ "ฉันไม่คิดว่านั่นเป็นความคิดที่ดี"
3. เลือกสรรพนามและคำลงท้ายให้เข้ากับตัวละคร ความสัมพันธ์ และแนวเรื่อง และใช้ให้คงที่ตลอดเรื่อง ถ้ามี genre ให้ยึดตาม genre ไม่งั้นเดาจาก title
   เช่น ละครจีนโบราณ/กำลังภายใน ใช้ ข้า/เจ้า, ละครหรือหนังสมัยใหม่ ใช้ ฉัน/ผม/นาย/เธอ, การ์ตูนเด็ก ใช้ ฉัน/ผม/นาย/เธอ แบบเด็กพูดกัน ห้ามใช้ ข้า/เจ้า
   speaker คือชื่อตัวละครที่พูด (ถ้ารู้) ใช้เลือกสรรพนามให้เข้ากับคนพูด
4. คงอารมณ์ของต้นฉบับ (โกรธ เยาะเย้ย อ้อนวอน เศร้า ตกใจ) ด้วยคำลงท้ายและคำอุทานที่คนไทยใช้จริง และใส่เครื่องหมาย ! ? … ตามน้ำเสียง เพราะนักพากย์ใช้เครื่องหมายเหล่านี้กำหนดน้ำเสียง
5. แต่ละท่อนมี min_chars ถึง max_chars คือจำนวนตัวอักษรไทย (ไม่นับสระบน สระล่าง และวรรณยุกต์) ที่พูดได้เต็มเวลาที่ตัวละครพูดท่อนนั้นด้วยความเร็วปกติ
   ให้แปลยาวอยู่ในช่วงนี้ เสียงพากย์จะได้จบพร้อมกับที่ตัวละครหยุดขยับปาก ห้ามเกิน max_chars
   ถ้าแปลแล้วสั้นกว่า min_chars ให้แปลส่วนที่ต้นฉบับพูดให้ครบก่อน แล้วจึงเติมคำลงท้าย คำอุทาน หรือคำซ้ำแบบภาษาพูดที่เข้ากับอารมณ์ ห้ามแต่งเนื้อหาใหม่
   ถ้ายาวเกิน max_chars ให้ตัดคำเสริม คำซ้ำ และคำลงท้ายที่ไม่จำเป็นก่อน ห้ามตัดชื่อเฉพาะ ตัวเลข คำปฏิเสธ หรือคำถาม
6. ชื่อคนและสถานที่ ให้สะกดตามที่ใช้กันในฉบับภาษาไทยของเรื่องนั้น และเหมือนกันทุกครั้ง ถ้ามี glossary ให้ใช้คำแปลตาม glossary ทุกตัวอักษร
7. แต่ละ sentence คือคำพูดต่อเนื่องที่ถูกตัดเป็นท่อนตามเวลา (parts) ให้แปลทั้ง sentence ให้เป็นธรรมชาติ แล้วแบ่งคำแปลคืนเป็นท่อนตามลำดับเดิม จำนวนท่อนต้องเท่ากับ parts ของต้นฉบับพอดี และแต่ละท่อนต้องเป็นความหมายของท่อนต้นฉบับนั้นเท่านั้น ห้ามรวมท่อนหรือย้ายเนื้อหาไปท่อนอื่น เพราะเสียงพากย์แต่ละท่อนจะเล่นตรงเวลาที่ตัวละครพูดท่อนนั้น
8. ตอบเป็น JSON อย่างเดียว ไม่มีคำอธิบาย"""

SYSTEM_PROMPT_EN = """You are a professional dubbing translator. Translate each line of drama dialogue into natural spoken English for a voice actor to read.
Rules:
1. Be accurate: every part must carry the full meaning of its source. Never add content the source does not say, never reinterpret or change what happens.
   Names, numbers, times, places, negations and questions must always match the source.
2. Write speech, not prose: use the conversational English people actually say in that situation, fitting the character and the genre (infer the genre from "title"), so it flows when read aloud.
   Do not translate word for word; use contractions and natural interjections, and avoid stiff or written phrasing unless the character really talks that way.
3. Keep the emotion of the original (anger, mockery, pleading, grief, shock) and mark it with ! ? … where the tone calls for it, because the voice actor reads the tone from punctuation.
4. Each part has "min_words" to "max_words": the length that fills the time the character speaks that part at a natural pace. Aim inside this range so the dub ends when the mouth stops moving, and never exceed "max_words".
   If shorter than "min_words", first translate everything the source says, then add natural fillers, repetition or interjections that fit the emotion; never invent new content.
   If longer than "max_words", tighten the wording and drop filler first; never drop names, numbers, negations or questions.
5. Romanize character and place names consistently (e.g. pinyin for Chinese names) and use the same spelling every time. When "glossary" is given, use its translations exactly. "speaker" is the name of the character speaking, when known; "genre", when given, sets the register.
6. Each sentence is continuous speech cut into timed parts. Translate the whole sentence naturally, then split your translation back into parts in the original order. Return exactly as many parts as the source has, and each part must carry only the meaning of its own source part: never merge parts or move content between them, because each dubbed part plays when the character speaks that part.
7. Reply with JSON only, no explanations."""

SHORTEN_PROMPT_TH = """ย่อบทพากย์ภาษาไทยแต่ละบรรทัดให้ไม่เกิน max_chars ตัวอักษร (ไม่นับสระบน สระล่าง และวรรณยุกต์) เพื่อให้พูดจบทันใน seconds วินาทีด้วยความเร็วปกติ
ใจความสำคัญต้องครบและตรงเดิม ห้ามตัดชื่อคน ชื่อสถานที่ ชื่องานหรือองค์กร ตัวเลข คำปฏิเสธ และคำถาม คงอารมณ์ของตัวละคร ห้ามเปลี่ยนสรรพนามและชื่อเฉพาะ
ย่อด้วยการเรียบเรียงใหม่ให้สั้นแบบที่คนไทยพูดจริง (ตัดคำซ้ำ คำเสริม หรือส่วนที่ไม่สำคัญ) ผลต้องยังเป็นประโยคพูดที่ลื่นปาก ไม่ห้วนเป็นวลีโทรเลข เก็บคำลงท้ายที่บอกน้ำเสียงไว้ (นะ สิ ล่ะ เหรอ ครับ)
ห้ามใช้คำย่อหรือตัวย่อ (ชม. กม. กก. รพ. ฯลฯ) ให้เขียนเต็มตามที่อ่านออกเสียง
ตอบเป็น JSON รูปแบบ {"lines":[{"id":1,"text":"..."}]} เท่านั้น"""

SHORTEN_PROMPT_EN = """Shorten each English dubbing line to at most "max_words" words so it can be spoken within its "seconds" value at a natural pace.
Keep the meaning and the character's emotion, and keep it natural spoken English. Never drop names (people, places, events, organizations), numbers, negations or questions.
Reply with JSON only, in the form {"lines":[{"id":1,"text":"..."}]}."""

EXPAND_PROMPT_TH = """บทพากย์ภาษาไทยบางบรรทัดสั้นกว่าเวลาที่ตัวละครพูดจริงมาก เสียงพากย์จบก่อนตัวละครหยุดขยับปาก
ขยายแต่ละบรรทัดให้ยาวประมาณ min_chars ถึง max_chars ตัวอักษร (ไม่นับสระบน สระล่าง และวรรณยุกต์) ให้พูดได้เต็ม seconds วินาที
กฎ:
1. ความหมายต้องตรงกับต้นฉบับ (source) ห้ามเพิ่มเนื้อหาที่ต้นฉบับไม่มี
2. ขยายด้วยสิ่งที่ต้นฉบับมีแต่คำแปลเดิมละไว้ก่อน แล้วจึงใช้คำอุทาน คำซ้ำ หรือคำลงท้ายแบบภาษาพูด (นะ น่ะ ล่ะ เลย จัง เนี่ย) ให้เข้ากับอารมณ์ของตัวละคร
3. ใช้ภาษาพูดที่คนไทยพูดจริงแบบงานพากย์ ห้ามเปลี่ยนสรรพนามและชื่อเฉพาะ
4. ถ้าขยายแล้วฟังไม่เป็นธรรมชาติ ให้คืนบทเดิม
ตอบเป็น JSON รูปแบบ {"lines":[{"id":1,"text":"..."}]} เท่านั้น"""

EXPAND_PROMPT_EN = """Some English dubbing lines are much shorter than the time the character actually speaks, so the dub ends while the mouth is still moving.
Expand each line to roughly "min_words" to "max_words" words so it fills its "seconds" value at a natural pace.
Keep the meaning of the original ("source"); never add content it does not have. First restore what the translation left out,
then use natural fillers, repetition or interjections that fit the character's emotion. If expanding would sound unnatural, return the line unchanged.
Reply with JSON only, in the form {"lines":[{"id":1,"text":"..."}]}."""

TURN_PROMPT = """You segment transcribed dialogue. Speaker diarization often merges two characters with similar voices into one line.
For each line, split the text at every point where a DIFFERENT character starts speaking (question and answer, a reply like "えっ?", "うん", "yeah", a change of who is addressed).
Do not split one character's continuous speech, repetitions, or self-talk. Use the neighbouring lines as context.
The pieces of a line, concatenated in order, must equal the original text exactly (same characters, no edits). One piece = no speaker change.
Reply with JSON only: {"lines":[{"id":1,"pieces":["...","..."]}]}"""

PROOFREAD_PROMPT_TH = """คุณคือผู้ตรวจบทถอดเสียงภาษาไทย บทนี้ได้จากระบบถอดเสียงอัตโนมัติ (Whisper) ซึ่งมักสะกดผิดตามเสียงที่ได้ยิน
เช่น พยัญชนะหรือสระเพี้ยน (หิบะทะลม → หิมะถล่ม, ปืนคลั้ง → ปืนครั้ง) คำติดกัน หรือมีตัวอักษรอังกฤษหลุดกลางคำ
กฎ:
1. แก้เฉพาะคำที่ถอดเสียงผิด โดยเลือกคำที่ออกเสียงใกล้ที่สุดและเข้ากับเรื่อง ห้ามแปลงสำนวน ห้ามเรียบเรียงใหม่
2. ห้ามลบคำ ห้ามเพิ่มเนื้อหา คำที่ฟังเพี้ยนให้เดาคำที่เสียงใกล้ที่สุดแทน ไม่ใช่ตัดทิ้ง
3. title คือชื่อคลิป ถ้าบรรทัดไหนพูดชื่อเรื่อง ให้สะกดตาม title ทุกตัวอักษร ชื่อตัวละครและสถานที่ให้สะกดตามที่ใช้กันในฉบับภาษาไทยของเรื่องนั้น และเหมือนกันทุกบรรทัด
4. ใส่ ! ? … ตามน้ำเสียงได้ เพราะนักพากย์ใช้กำหนดน้ำเสียง
5. บรรทัดที่ถูกอยู่แล้ว ให้คืนข้อความเดิม
6. ตอบเป็น JSON รูปแบบ {"lines":[{"id":1,"text":"..."}]} ครบทุก id เท่านั้น"""

PROOFREAD_PROMPT_EN = """You proofread an automatic (Whisper) English transcript of drama dialogue.
Rules:
1. Fix only misheard or misspelled words, choosing the closest-sounding word that fits the story. Do not rephrase or reorder.
2. Never delete words or add content: replace a garbled word with its closest-sounding guess instead of dropping it.
3. "title" is the video title: when a line says the title, spell it exactly as in "title". Spell character and place names the way the official release does, consistently on every line.
4. You may add ! ? … where the tone calls for it.
5. Return lines that are already correct unchanged.
6. Reply with JSON only, in the form {"lines":[{"id":1,"text":"..."}]}, covering every id."""

MOOD_PROMPT_TH = """คุณคือผู้กำกับการพากย์ เลือกอารมณ์ของเสียงพากย์ให้แต่ละบรรทัด จากบทต้นฉบับ (source) บทพากย์ (text) และบรรทัดรอบ ๆ
แต่ละบรรทัดมี moods คืออารมณ์ที่เลือกได้ และ excite คือความตื่นเต้นที่วัดจากเสียงต้นฉบับ (0 = ปกติของตัวละครนั้น, บวก = ดัง/ตื่นเต้นกว่าปกติ, ลบ = เบา/เนิบกว่าปกติ) ถ้ามี
ความหมายของอารมณ์: angry = โกรธ ตะโกน ดุ, sad = เศร้า ร้องไห้ ผิดหวัง, happy = ดีใจ ตื่นเต้น หัวเราะ, whisper = กระซิบ พูดเบา ๆ แอบพูด, scared = ตกใจ กลัว ตื่นตระหนก
กฎ:
1. ตอบ normal เมื่อเป็นบทพูดทั่วไปหรือไม่แน่ใจ เลือกอารมณ์อื่นเฉพาะเมื่อบทและน้ำเสียงชัดเจน เพราะเสียงอารมณ์ที่ผิดฟังแย่กว่าเสียงปกติ
2. เลือกได้เฉพาะ normal หรืออารมณ์ใน moods ของบรรทัดนั้น
3. ตอบเป็น JSON รูปแบบ {"lines":[{"id":1,"mood":"normal"}]} ครบทุก id เท่านั้น"""

_client = None
_local = None


# ---------------- ตัวช่วย ----------------
def estimate_seconds(text: str, target_lang: str = "th") -> float:
    """ประมาณเวลาพูด: ภาษาไทยนับตัวอักษรที่ไม่ใช่สระบนล่างและวรรณยุกต์ ภาษาอังกฤษนับคำ"""
    if target_lang == "en":
        return len(text.split()) / settings.en_words_per_sec
    base = sum(1 for ch in text if not ch.isspace() and unicodedata.category(ch) != "Mn")
    return base / settings.thai_chars_per_sec


def max_length(seconds: float, target_lang: str = "th") -> int:
    """ความยาวบทมากสุดที่พูดทันในเวลานี้ด้วยความเร็วปกติ (ไทย = ตัวอักษรแบบ estimate_seconds, อังกฤษ = คำ)"""
    rate = settings.en_words_per_sec if target_lang == "en" else settings.thai_chars_per_sec
    return max(1, int(seconds * rate))


def budgets(utts: list[Utterance]) -> dict[int, float]:
    """เวลาที่ใช้พูดแต่ละท่อนได้จริง: ช่วงที่นักแสดงพูด บวกช่วงเงียบก่อนประโยคถัดไปอีกเล็กน้อย
    (ตอนพากย์ยอมให้เสียงล้นเข้าช่วงเงียบได้ แต่ไม่ทับประโยคถัดไป)"""
    order = sorted(utts, key=lambda u: u.start)
    out = {}
    for i, u in enumerate(order):
        gap = (order[i + 1].start - u.end) if i + 1 < len(order) else settings.fit_slack
        out[u.id] = u.duration + min(max(gap, 0.0), settings.fit_slack)
    return out


def _speaker_label(speaker: str, hints: dict) -> str:
    return (hints.get("names") or {}).get(speaker) or speaker


def _glossary(hints: dict) -> list[str]:
    return [line.strip() for line in (hints.get("glossary") or "").splitlines() if line.strip()][:60]


def _parse_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"ไม่พบ JSON ในคำตอบ: {text[:200]}")
    try:
        # โมเดลบางครั้งตอบ JSON ซ้ำหลายก้อนต่อกัน ใช้ก้อนแรก
        return json.JSONDecoder().raw_decode(text[start:])[0]
    except json.JSONDecodeError:
        salvaged = _salvage_sentences(text[start:])
        if salvaged:
            return salvaged
        raise


def _salvage_sentences(text: str) -> Optional[dict]:
    """กู้คำตอบที่วงเล็บปิดผิดลำดับ (เช่น ["..."}]) โดยดึง id กับรายการ parts ออกมาทีละประโยค"""
    out = []
    for m in re.finditer(r'"id"\s*:\s*(\d+)[^\[\]]*?"parts"\s*:\s*\[((?:\s*"(?:[^"\\]|\\.)*"\s*,?)*)', text):
        if any(s["id"] == int(m.group(1)) for s in out):
            continue
        parts = [json.loads(p) for p in re.findall(r'"(?:[^"\\]|\\.)*"', m.group(2))]
        out.append({"id": int(m.group(1)), "parts": parts})
    return {"sentences": out} if out else None


def _chat(system: str, user: str, temperature: Optional[float] = None, max_tokens: int = 4096) -> str:
    global _client
    if not settings.typhoon_api_key:
        raise RuntimeError("ต้องตั้งค่า TYPHOON_API_KEY (สมัครฟรีที่ playground.opentyphoon.ai)")
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=settings.typhoon_api_key, base_url=settings.typhoon_base_url)
    last_error: Optional[Exception] = None
    for attempt in range(4):
        try:
            resp = _client.chat.completions.create(
                model=settings.typhoon_model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=settings.typhoon_temperature if temperature is None else temperature,
                max_tokens=max_tokens,
                **({"reasoning_effort": settings.typhoon_reasoning_effort} if settings.typhoon_reasoning_effort else {}),
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001  rate limit / network
            last_error = exc
            wait = 2 ** attempt * 2
            log.warning("Typhoon API error (%s), retry in %ss", exc, wait)
            time.sleep(wait)
    raise RuntimeError(f"เรียก Typhoon API ไม่สำเร็จ: {last_error}")


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


FOREIGN_SCRIPT = re.compile(r"[぀-ヿ㐀-鿿가-힯豈-﫿]")


def _item_text(item) -> str:
    """ดึงข้อความจากคำตอบโมเดล ซึ่งบางครั้งห่อมาเป็น {"text": ..} หรือ ["..."] แทนข้อความเปล่า
    หรือเป็น JSON ทั้งก้อนอยู่ในข้อความ ({"parts": ["..."]}) ถ้าไม่แกะออก เสียงพากย์จะอ่านวงเล็บและคำว่า parts"""
    if isinstance(item, str) and item.lstrip().startswith(("{", "[")):
        try:
            item = json.loads(item)
        except json.JSONDecodeError:
            pass
    if isinstance(item, dict):
        item = item.get("text") or item.get("parts") or item.get("th") or item.get("en") or ""
    if isinstance(item, list):
        return " ".join(t for t in map(_item_text, item) if t)
    return str(item).strip()


# ---------------- แปลผ่าน API ----------------
def _group_lines(utts: list[Utterance], max_parts: int = 4) -> list[list[Utterance]]:
    """รวมท่อนที่น่าจะเป็นประโยคเดียวกัน: คนเดิม พูดต่อเนื่อง (เว้นไม่เกิน 1.5 วินาที) และท่อนก่อนยังไม่จบประโยค

    ถ้าส่งไปแปลเป็นบรรทัดเดี่ยว ๆ โมเดลจะประกอบประโยคใหม่เองแล้วย้ายความหมายข้ามบรรทัด บทจึงเลื่อนไม่ตรงปาก
    (เจอบ่อยกับภาษาจีนที่ Whisper แทบไม่ใส่วรรคตอน)
    """
    groups: list[list[Utterance]] = []
    for u in utts:
        g = groups[-1] if groups else None
        if (g and len(g) < max_parts and u.speaker == g[-1].speaker and u.start - g[-1].end <= 1.5
                and not g[-1].source.strip().endswith(SENTENCE_END)):
            g.append(u)
        else:
            groups.append([u])
    return groups


def _group_batches(groups: list[list[Utterance]], max_lines: int):
    batch: list[list[Utterance]] = []
    for g in groups:
        if batch and sum(map(len, batch)) + len(g) > max_lines:
            yield batch
            batch = []
        batch.append(g)
    if batch:
        yield batch


def _groups_prompt(groups: list[list[Utterance]], lang: str, target: str,
                   context: list[Utterance], title: str = "", hints: Optional[dict] = None) -> tuple[str, str]:
    names = LANG_NAMES_EN if target == "en" else LANG_NAMES
    hints = hints or {}
    budget = hints.get("budgets") or {}
    lo_key, limit_key = ("min_words", "max_words") if target == "en" else ("min_chars", "max_chars")
    glossary = _glossary(hints)
    payload = {
        "title": title,
        **({"genre": hints["genre"]} if hints.get("genre") else {}),
        **({"glossary": glossary} if glossary else {}),
        "source_language": names.get(lang, lang),
        "previous_lines": [{"speaker": _speaker_label(u.speaker, hints), "text": u.target} for u in context],
        "sentences": [{"id": g[0].id, "speaker": _speaker_label(g[0].speaker, hints),
                       "parts": [{"seconds": round(budget.get(u.id, u.duration), 1),
                                  # ขั้นต่ำ 80% ของเวลาที่ตัวละครพูดจริง (ไม่นับช่วงเงียบท้ายประโยค) ให้เสียงพากย์จบพร้อมปาก
                                  lo_key: max(1, int(max_length(u.duration, target) * 0.8)) if u.duration >= 1.0 else 1,
                                  limit_key: max_length(budget.get(u.id, u.duration), target),
                                  "text": u.source} for u in g]}
                      for g in groups],
    }
    if target == "en":
        return SYSTEM_PROMPT_EN, (
            "Translate the sentences in \"sentences\" into English (\"title\" is the video title and \"previous_lines\" "
            "are earlier lines, both for context only, do not translate them). Give exactly one translated part per source part.\n"
            'Reply as {"sentences":[{"id":1,"parts":["part 1","part 2"]}]}\n\n'
            + json.dumps(payload, ensure_ascii=False))
    return SYSTEM_PROMPT_TH, (
        "แปล sentences เป็นภาษาไทย (title คือชื่อคลิป previous_lines คือบทก่อนหน้า ไว้ดูบริบท ไม่ต้องแปล) "
        "ตอบท่อนแปลให้ครบหนึ่งต่อหนึ่งกับ parts ของต้นฉบับ\n"
        'ตอบรูปแบบ {"sentences":[{"id":1,"parts":["ท่อนที่ 1","ท่อนที่ 2"]}]}\n\n'
        + json.dumps(payload, ensure_ascii=False))


def _translate_groups(groups: list[list[Utterance]], lang: str, target: str, context: list[Utterance],
                      title: str = "", hints: Optional[dict] = None) -> None:
    pending = groups
    foreign: dict[int, list[str]] = {}  # คำตอบที่ครบแต่มีอักษรต้นฉบับปน ไว้ใช้เมื่อแปลใหม่แล้วยังไม่ผ่าน
    single = len(groups) == 1 and len(groups[0]) == 1
    for attempt in range(3 if single else 2):
        system, user = _groups_prompt(pending, lang, target, context, title, hints)
        # จำกัดความยาวคำตอบตามจำนวนท่อน บางครั้งโมเดลพิมพ์วนไม่หยุดเป็นหมื่นตัวอักษร ทั้งช้าและอ่าน JSON ไม่ออก
        # รอบที่ลองใหม่เพิ่มความสุ่ม คำตอบจะได้ไม่พังซ้ำแบบเดิม
        max_tokens = min(4096, 400 + 200 * sum(map(len, pending)))
        temperature = None if attempt == 0 else 0.7
        try:
            result = _parse_json(_chat(system, user, temperature, max_tokens))
        except (ValueError, json.JSONDecodeError) as exc:
            log.warning("parse error (attempt %d): %s", attempt + 1, exc)
            continue
        by_id = {int(s["id"]): s.get("parts") for s in result.get("sentences", []) if "id" in s}
        retry = []
        for g in pending:
            parts = by_id.get(g[0].id)
            texts = [_item_text(p) for p in parts] if isinstance(parts, list) else []
            # จำนวนท่อนต้องตรงพอดี ไม่งั้นแปลว่าโมเดลรวมหรือย้ายท่อน บทจะเลื่อนไม่ตรงเวลา
            # และต้องไม่มีอักษรต้นฉบับ (จีน ฯลฯ) หลุดมา เพราะโมเดลพากย์อ่านไม่ได้
            ok = len(texts) == len(g) and any(texts)
            if ok and not any(FOREIGN_SCRIPT.search(t) for t in texts):
                for u, text in zip(g, texts):
                    u.target = text
            else:
                if ok:
                    foreign[g[0].id] = texts
                retry.append(g)
        if not retry:
            return
        log.warning("sentences %s: wrong part count or untranslated text, retrying", [g[0].id for g in retry])
        pending = retry

    done = lambda: [u for g in groups for u in g if u.target]  # noqa: E731
    if len(pending) > 1:  # คำตอบยาวจนถูกตัดหรืออ่านไม่ออก → แบ่งครึ่งแล้วแปลใหม่
        mid = len(pending) // 2
        _translate_groups(pending[:mid], lang, target, context, title, hints)
        _translate_groups(pending[mid:], lang, target, (context + done())[-6:], title, hints)
    elif len(pending[0]) > 1:  # แบ่งท่อนให้ตรงไม่ได้ → แปลทีละท่อน
        for u in pending[0]:
            _translate_groups([[u]], lang, target, (context + done())[-6:], title, hints)
    else:
        _translate_plain(pending[0][0], lang, target, context, foreign.get(pending[0][0].id))


def _translate_plain(u: Utterance, lang: str, target: str, context: list[Utterance],
                     foreign: Optional[list[str]] = None) -> None:
    """ทางสุดท้ายของประโยคเดียวที่แปลแบบ JSON ไม่ผ่าน: ขอคำแปลเป็นข้อความเปล่า ไม่ต้องจัดรูปแบบ
    ถ้ายังไม่ได้ ใช้คำตอบที่ตัดอักษรต้นฉบับทิ้ง หรือปล่อยว่างให้ผู้ใช้แก้ในหน้าตรวจบท ดีกว่าให้ทั้งงานล้ม"""
    names = LANG_NAMES_EN if target == "en" else LANG_NAMES
    before = " / ".join(x.target for x in context[-3:])
    if target == "en":
        system = SYSTEM_PROMPT_EN
        user = (f"Earlier lines (context only): {before}\n"
                f"Translate this {names.get(lang, lang)} line into English. Reply with the translation only.\n{u.source}")
    else:
        system = SYSTEM_PROMPT_TH
        user = (f"บทก่อนหน้า (ไว้ดูบริบท): {before}\n"
                f"แปลบทพูดภาษา{names.get(lang, lang)}นี้เป็นภาษาไทย ตอบเฉพาะคำแปลบรรทัดเดียว ไม่ต้องมีคำอธิบาย\n{u.source}")
    for temperature in (0.3, 0.8):
        try:
            text = _chat(system, user, temperature, max_tokens=200)
        except RuntimeError:
            break
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip().strip('"').splitlines()
        text = text[0].strip() if text else ""
        if text and not FOREIGN_SCRIPT.search(text) and len(text) < 20 * max(len(u.source), 5):
            u.target = text
            return
    if foreign:
        u.target = " ".join(FOREIGN_SCRIPT.sub(" ", foreign[0]).split())
    else:
        log.error("line %d: translation failed, left empty for review", u.id)


# ---------------- แปลบนเครื่อง (Typhoon Translate อังกฤษ → ไทย) ----------------
def _translate_local(text: str) -> str:
    global _local
    if _local is None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        tok = AutoTokenizer.from_pretrained(settings.typhoon_translate_model)
        model = AutoModelForCausalLM.from_pretrained(
            settings.typhoon_translate_model, torch_dtype=torch.bfloat16, device_map="auto")
        _local = (tok, model)
    tok, model = _local
    messages = [{"role": "system", "content": "Translate the following text into Thai."},
                {"role": "user", "content": text}]
    inputs = tok.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt").to(model.device)
    out = model.generate(inputs, max_new_tokens=512, do_sample=True, temperature=0.2, top_p=0.95)
    return tok.decode(out[0][inputs.shape[-1]:], skip_special_tokens=True).strip()


def unload() -> None:
    global _local
    _local = None


_CLOCK = re.compile(r"(?<![\d:])([01]?\d|2[0-4]):([0-5]\d)(?![\d:])(\s*(?:น\.|นาฬิกา))?")


def _thai_clock(h: int, m: int) -> str:
    """ชั่วโมง นาที → เวลาแบบที่คนไทยพูด (22:30 → สี่ทุ่มครึ่ง, 07:15 → เจ็ดโมงเช้าสิบห้านาที)"""
    from pythainlp.util import num_to_thaiword as n

    h %= 24
    if h == 0:
        head = "เที่ยงคืน"
    elif h <= 5:
        head = f"ตี{n(h)}"
    elif h <= 11:
        head = f"{n(h)}โมงเช้า" if h < 11 else "สิบเอ็ดโมง"
    elif h == 12:
        head = "เที่ยง"
    elif h == 13:
        head = "บ่ายโมง"
    elif h <= 15:
        head = f"บ่าย{n(h - 12)}โมง"
    elif h <= 18:
        head = f"{n(h - 12)}โมงเย็น"
    else:
        head = f"{n(h - 18)}ทุ่ม"
    if m == 0:
        return head
    if m == 30 and h not in (0, 12):
        return head + "ครึ่ง"
    return f"{head}{n(m)}นาที"


def speak_times(text: str) -> str:
    """เวลาแบบตัวเลข (22:00) ในบทไทย → คำพูด นักพากย์และโมเดลเสียงอ่านเลขเวลาไม่ถูก"""
    return _CLOCK.sub(lambda x: _thai_clock(int(x.group(1)), int(x.group(2))), text)


# หน่วยย่อ ขยายเฉพาะเมื่อตามหลังตัวเลขหรือคำบอกจำนวน ("น่าชม." ไม่ใช่ชั่วโมง)
_UNITS = {"ชม.": "ชั่วโมง", "กม.": "กิโลเมตร", "กก.": "กิโลกรัม", "ซม.": "เซนติเมตร", "มม.": "มิลลิเมตร",
          "ตร.ม.": "ตารางเมตร", "ลบ.ม.": "ลูกบาศก์เมตร"}
_COUNT = r"(?:[\d๐-๙]|หนึ่ง|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า|สิบ|ยี่สิบ|เอ็ด|ร้อย|พัน|หมื่น|แสน|ล้าน|ครึ่ง|กี่|หลาย|ไม่กี่)"
_UNIT_RE = re.compile(rf"({_COUNT})(\s*)(" + "|".join(re.escape(k) for k in sorted(_UNITS, key=len, reverse=True)) + ")")
# ตัวย่อที่มีจุดชัดเจน ขยายได้ทุกที่
_ABBR = {"ฯลฯ": "และอื่นๆ", "กทม.": "กรุงเทพ", "รพ.": "โรงพยาบาล", "ร.ร.": "โรงเรียน", "ผอ.": "ผู้อำนวยการ",
         "นศ.": "นักศึกษา", "ดร.": "ดอกเตอร์", "พ.ศ.": "พุทธศักราช", "ค.ศ.": "คริสต์ศักราช",
         "ม.ค.": "มกราคม", "ก.พ.": "กุมภาพันธ์", "มี.ค.": "มีนาคม", "เม.ย.": "เมษายน", "พ.ค.": "พฤษภาคม",
         "มิ.ย.": "มิถุนายน", "ก.ค.": "กรกฎาคม", "ส.ค.": "สิงหาคม", "ก.ย.": "กันยายน", "ต.ค.": "ตุลาคม",
         "พ.ย.": "พฤศจิกายน", "ธ.ค.": "ธันวาคม"}
_ABBR_RE = re.compile("|".join(re.escape(k) for k in sorted(_ABBR, key=len, reverse=True)))


def spoken(text: str) -> str:
    """บทไทย → แบบที่อ่านออกเสียงได้ตรง: เวลาเป็นคำพูด ตัวย่อเป็นคำเต็ม (โมเดลเสียงอ่านตามตัวอักษร "ชม." จึงกลายเป็น "ชม")"""
    text = speak_times(text)
    text = _UNIT_RE.sub(lambda x: x.group(1) + x.group(2) + _UNITS[x.group(3)], text)
    text = _ABBR_RE.sub(lambda x: _ABBR[x.group(0)], text)
    return text.replace("ฯ", "")


# ---------------- ฟังก์ชันหลัก ----------------
def translate_utterances(utts: list[Utterance], lang: str, target: str = "th",
                         on_progress: Optional[Callable[[float], None]] = None,
                         check_cancel: Optional[Callable[[], None]] = None, title: str = "",
                         hints: Optional[dict] = None) -> None:
    """hints: genre (แนวเรื่อง), glossary (ชื่อเฉพาะ บรรทัดละคำ เช่น ドラえもん = โดราเอมอน), names (ผู้พูด → ชื่อตัวละคร)"""
    hints = {**(hints or {}), "budgets": budgets(utts)}
    if lang == target:
        for u in utts:
            u.target = u.target or u.source
        if settings.typhoon_api_key:
            proofread(utts, target, on_progress, check_cancel, title)
        return

    # โมเดลแปลบนเครื่องต้องใช้การ์ดจอ โหมด modal จึงแปลด้วย Typhoon API เสมอ
    if target == "th" and lang == "en" and settings.translate_en_local and settings.worker != "modal":
        for i, u in enumerate(utts):
            if check_cancel:
                check_cancel()
            u.target = _translate_local(u.source)
            if on_progress:
                on_progress((i + 1) / len(utts))
        return

    done = 0
    for batch in _group_batches(_group_lines(utts), settings.translate_batch_size):
        if check_cancel:
            check_cancel()
        context = [u for u in utts if u.target and u.id < batch[0][0].id][-6:]
        _translate_groups(batch, lang, target, context, title, hints)
        if target == "th":
            for g in batch:
                for u in g:
                    u.target = spoken(u.target)
        done += sum(map(len, batch))
        if on_progress:
            on_progress(done / len(utts))


def detect_moods(lines: list[tuple[Utterance, list[str]]], context: list[Utterance],
                 arousal: Optional[dict[int, float]] = None) -> dict[int, str]:
    """เลือกอารมณ์ให้แต่ละบรรทัด (บรรทัด, อารมณ์ที่เลือกได้) → id → อารมณ์ ("" = ปกติ)
    เรียกไม่สำเร็จหรือตอบอารมณ์ที่ไม่มีให้เลือก ใช้เสียงปกติ"""
    order = {u.id: i for i, u in enumerate(context)}
    out: dict[int, str] = {}
    for batch in _chunks(lines, settings.translate_batch_size):
        ids = [order.get(u.id, 0) for u, _ in batch]
        around = [u for u in context[max(0, min(ids) - 3): max(ids) + 4] if u.id not in {b.id for b, _ in batch}]
        payload = {
            "nearby_lines": [{"speaker": u.speaker, "text": u.target} for u in around],
            "lines": [{"id": u.id, "speaker": u.speaker, "source": u.source, "text": u.target, "moods": moods,
                       **({"excite": arousal[u.id]} if arousal and u.id in arousal else {})} for u, moods in batch],
        }
        try:
            result = _parse_json(_chat(MOOD_PROMPT_TH, json.dumps(payload, ensure_ascii=False), temperature=0.1,
                                       max_tokens=min(4096, 200 + 40 * len(batch))))
            got = {int(x["id"]): str(x.get("mood", "")) for x in result.get("lines", []) if "id" in x}
        except Exception as exc:  # noqa: BLE001
            log.warning("mood detection failed: %s", exc)
            got = {}
        for u, moods in batch:
            m = got.get(u.id, "")
            out[u.id] = m if m in moods else ""
    return out


def proofread(utts: list[Utterance], target: str = "th",
              on_progress: Optional[Callable[[float], None]] = None,
              check_cancel: Optional[Callable[[], None]] = None, title: str = "") -> None:
    """ต้นฉบับเป็นภาษาเดียวกับปลายทาง: ไม่ต้องแปล แต่บทถอดเสียงผิดจะถูกพากย์ผิดตามไปด้วย จึงให้โมเดลแก้คำผิด
    แก้ได้ไม่ผ่าน (คำตอบพัง จำนวนบรรทัดไม่ครบ หรือยาวต่างจากเดิมมากจนน่าจะเรียบเรียงใหม่) ใช้บทเดิม"""
    prompt = PROOFREAD_PROMPT_EN if target == "en" else PROOFREAD_PROMPT_TH
    done = 0
    for batch in _chunks(utts, settings.translate_batch_size):
        if check_cancel:
            check_cancel()
        before = [u.target for u in utts if u.id < batch[0].id][-6:]
        payload = {"title": title, "previous_lines": before,
                   "lines": [{"id": u.id, "speaker": u.speaker, "text": u.target} for u in batch]}
        try:
            # ใส่ชื่อคลิปไว้หัวข้อความด้วย อยู่แค่ใน JSON โมเดลมักไม่เอาไปเทียบตอนแก้ชื่อเรื่องที่ถอดเสียงเพี้ยน
            head = f"title: {title}\n\n" if title else ""
            result = _parse_json(_chat(prompt, head + json.dumps(payload, ensure_ascii=False), temperature=0.2,
                                       max_tokens=min(4096, 400 + 150 * len(batch))))
            by_id = {int(x["id"]): _item_text(x) for x in result.get("lines", []) if "id" in x}
        except Exception as exc:  # noqa: BLE001
            log.warning("proofread failed: %s", exc)
            by_id = {}
        for u in batch:
            text = by_id.get(u.id)
            if text and not FOREIGN_SCRIPT.search(text) and 0.5 <= len(text) / max(len(u.target), 1) <= 1.8:
                u.target = text
        done += len(batch)
        if on_progress:
            on_progress(done / len(utts))


def fit_lengths(utts: list[Utterance], target: str = "th", max_speedup: float = 1.35) -> None:
    """ปรับความยาวบทให้พอดีเวลาที่ตัวละครพูด
    ย่อบทที่คาดว่ายาวเกินเวลาที่มี ให้พูดได้ด้วยความเร็วปกติ (สองรอบ รอบสองเฉพาะบรรทัดที่ยังยาวเกิน)
    แล้วขยายบทที่สั้นกว่าเวลาพูดจริงมาก (ไม่ยืดเสียง เสียงยืดฟังยานไม่เป็นธรรมชาติ)"""
    if not settings.typhoon_api_key:
        return
    tolerance = min(max_speedup, settings.fit_tolerance)
    budget = budgets(utts)
    for _ in range(2):
        too_long = [u for u in utts if u.duration > 0 and u.target
                    and estimate_seconds(u.target, target) > budget[u.id] * tolerance]
        if not too_long:
            break
        log.info("shorten %d lines: %s", len(too_long), [u.id for u in too_long])
        for batch in _chunks(too_long, settings.translate_batch_size):
            shorten(batch, target, target_ratio=tolerance, budgets=budget)
    # ท่อนสั้น ๆ (ไม่ถึง 1 วินาที) มักเป็นคำเดียว ขยายแล้วไม่เป็นธรรมชาติ
    too_short = [u for u in utts if settings.fit_min_ratio > 0 and u.duration >= 1.0 and u.target.strip()
                 and estimate_seconds(u.target, target) < u.duration * settings.fit_min_ratio]
    if too_short:
        log.info("lengthen %d lines: %s", len(too_short), [u.id for u in too_short])
        for batch in _chunks(too_short, settings.translate_batch_size):
            lengthen(batch, target, tolerance)
    if target == "th":  # บทที่ย่อหรือขยายแล้วอาจมีตัวย่อกลับมา
        for u in utts:
            u.target = spoken(u.target)


def lengthen(batch: list[Utterance], target: str = "th", tolerance: float = 1.1) -> None:
    """ขยายบทให้ยาวราว 80–100% ของเวลาที่ตัวละครพูด โดยความหมายตรงต้นฉบับ
    ใช้เฉพาะคำตอบที่ยาวขึ้นจริงและไม่เกินเวลาที่มี ขยายไม่ได้ก็ใช้บทเดิม"""
    lo_key, hi_key = ("min_words", "max_words") if target == "en" else ("min_chars", "max_chars")
    payload = [{"id": u.id, "seconds": round(u.duration, 1), lo_key: max_length(u.duration * 0.8, target),
                hi_key: max_length(u.duration, target), "source": u.source, "text": u.target} for u in batch]
    prompt = EXPAND_PROMPT_EN if target == "en" else EXPAND_PROMPT_TH
    try:
        result = _parse_json(_chat(prompt, json.dumps({"lines": payload}, ensure_ascii=False)))
        by_id = {int(x["id"]): _item_text(x) for x in result.get("lines", []) if "id" in x}
        for u in batch:
            text = by_id.get(u.id)
            if (text and not FOREIGN_SCRIPT.search(text)
                    and estimate_seconds(u.target, target) < estimate_seconds(text, target) <= u.duration * tolerance):
                u.target = text
    except Exception as exc:  # noqa: BLE001
        log.warning("lengthen failed: %s", exc)


def shorten(batch: list[Utterance], target: str = "th", target_ratio: float = 1.0,
            budgets: Optional[dict[int, float]] = None) -> None:
    limit_key = "max_words" if target == "en" else "max_chars"
    payload = []
    for u in batch:
        sec = (budgets or {}).get(u.id, u.duration) * target_ratio
        payload.append({"id": u.id, "seconds": round(sec, 1), limit_key: max_length(sec, target), "text": u.target})
    prompt = SHORTEN_PROMPT_EN if target == "en" else SHORTEN_PROMPT_TH
    try:
        result = _parse_json(_chat(prompt, json.dumps({"lines": payload}, ensure_ascii=False)))
        by_id = {int(x["id"]): _item_text(x) for x in result.get("lines", []) if "id" in x}
        for u in batch:
            text = by_id.get(u.id)
            # ใช้เฉพาะคำตอบที่สั้นลงจริง บางครั้งโมเดลคืนบทเดิมหรือยาวขึ้น
            if (text and not FOREIGN_SCRIPT.search(text)
                    and estimate_seconds(text, target) < estimate_seconds(u.target, target)):
                u.target = text
    except Exception as exc:  # noqa: BLE001  ย่อไม่ได้ก็ใช้บทเดิม แล้วไปเร่งความเร็วแทน
        log.warning("shorten failed: %s", exc)


def propose_turns(utts: list[Utterance], batch_size: int = 25) -> dict[int, list[str]]:
    """id ประโยค → ข้อความที่ตัดตามคนพูด (เฉพาะประโยคที่ควรตัด) จากความหมายของบท
    ระบบแยกผู้พูดฟังแค่เสียง สองคนเสียงคล้ายกันพูดโต้ตอบเร็ว ๆ จะได้ท่อนเดียว แต่บทบอกได้ชัด (ถาม/ตอบ คำรับ)
    ใช้เฉพาะคำตอบที่ต่อกันแล้วตรงกับบทเดิมทุกตัวอักษร (ไม่นับช่องว่าง) เวลาของแต่ละชิ้นหาจากเวลาของคำ"""
    order = sorted(utts, key=lambda u: u.start)
    src = {u.id: u.source for u in order}
    out: dict[int, list[str]] = {}
    for i in range(0, len(order), batch_size):
        batch = [{"id": u.id, "text": u.source} for u in order[i:i + batch_size]]
        try:
            result = _parse_json(_chat(TURN_PROMPT, json.dumps({"lines": batch}, ensure_ascii=False),
                                       temperature=0.1, max_tokens=8192))
        except Exception as exc:  # noqa: BLE001  เสนอไม่ได้ก็ใช้การแยกผู้พูดเดิม
            log.warning("propose turns failed: %s", exc)
            continue
        for x in result.get("lines", []):
            try:
                uid, pieces = int(x["id"]), [str(p) for p in x.get("pieces") or []]
            except (KeyError, TypeError, ValueError):
                continue
            plain = lambda t: t.replace(" ", "")  # noqa: E731
            if uid in src and len(pieces) > 1 and plain("".join(pieces)) == plain(src[uid]) and all(plain(p) for p in pieces):
                out[uid] = pieces
    return out
