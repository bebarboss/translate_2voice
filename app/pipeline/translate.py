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
1. ใช้ภาษาพูดที่เป็นธรรมชาติแบบคนไทยคุยกันจริง ไม่แปลตรงตัว
2. เลือกสรรพนามและคำลงท้ายให้เข้ากับตัวละคร ความสัมพันธ์ และแนวเรื่อง (เช่น ละครจีนโบราณใช้ ข้า/เจ้า, ละครสมัยใหม่ใช้ ฉัน/นาย/เธอ) และใช้ให้คงที่ตลอดเรื่อง ดูแนวเรื่องได้จาก title
3. คงอารมณ์ของต้นฉบับ (โกรธ เยาะเย้ย อ้อนวอน เศร้า ตกใจ) ด้วยคำลงท้ายและคำอุทานที่คนไทยใช้จริง และใส่เครื่องหมาย ! ? … ตามน้ำเสียง เพราะนักพากย์ใช้เครื่องหมายเหล่านี้กำหนดน้ำเสียง
4. ความยาวของแต่ละท่อนต้องพูดจบได้ภายในเวลา seconds ของท่อนนั้น ที่ความเร็วพูดปกติประมาณ 6 พยางค์ต่อวินาที ถ้ายาวเกินให้ย่อโดยคงความหมายหลัก
5. ชื่อคนและสถานที่ ให้ถอดเสียงเป็นอักษรไทยแบบเดียวกันทุกครั้ง
6. แต่ละ sentence คือคำพูดต่อเนื่องที่ถูกตัดเป็นท่อนตามเวลา (parts) ให้แปลทั้ง sentence ให้เป็นธรรมชาติ แล้วแบ่งคำแปลคืนเป็นท่อนตามลำดับเดิม จำนวนท่อนต้องเท่ากับ parts ของต้นฉบับพอดี และแต่ละท่อนต้องเป็นความหมายของท่อนต้นฉบับนั้นเท่านั้น ห้ามรวมท่อนหรือย้ายเนื้อหาไปท่อนอื่น เพราะเสียงพากย์แต่ละท่อนจะเล่นตรงเวลาที่ตัวละครพูดท่อนนั้น
7. ตอบเป็น JSON อย่างเดียว ไม่มีคำอธิบาย"""

SYSTEM_PROMPT_EN = """You are a professional dubbing translator. Translate each line of drama dialogue into natural spoken English for a voice actor to read.
Rules:
1. Use natural, conversational English that fits the character and the genre (infer the genre from "title"); do not translate word for word.
2. Keep the emotion of the original (anger, mockery, pleading, grief, shock) and mark it with ! ? … where the tone calls for it, because the voice actor reads the tone from punctuation.
3. Keep each part short enough to be spoken within its "seconds" value at about 2.5 words per second. Shorten if needed while keeping the core meaning.
4. Romanize character and place names consistently (e.g. pinyin for Chinese names) and use the same spelling every time.
5. Each sentence is continuous speech cut into timed parts. Translate the whole sentence naturally, then split your translation back into parts in the original order. Return exactly as many parts as the source has, and each part must carry only the meaning of its own source part: never merge parts or move content between them, because each dubbed part plays when the character speaks that part.
6. Reply with JSON only, no explanations."""

SHORTEN_PROMPT_TH = """ย่อบทพากย์ภาษาไทยแต่ละบรรทัดให้พูดจบได้ภายใน seconds วินาที (ประมาณ 6 พยางค์ต่อวินาที)
คงความหมายและอารมณ์ของตัวละครไว้ ใช้ภาษาพูดที่เป็นธรรมชาติ
ตอบเป็น JSON รูปแบบ {"lines":[{"id":1,"text":"..."}]} เท่านั้น"""

SHORTEN_PROMPT_EN = """Shorten each English dubbing line so it can be spoken within its "seconds" value (about 2.5 words per second).
Keep the meaning and the character's emotion, and keep it natural spoken English.
Reply with JSON only, in the form {"lines":[{"id":1,"text":"..."}]}."""

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

_client = None
_local = None


# ---------------- ตัวช่วย ----------------
def estimate_seconds(text: str, target_lang: str = "th") -> float:
    """ประมาณเวลาพูด: ภาษาไทยนับตัวอักษรที่ไม่ใช่สระบนล่างและวรรณยุกต์ ภาษาอังกฤษนับคำ"""
    if target_lang == "en":
        return len(text.split()) / settings.en_words_per_sec
    base = sum(1 for ch in text if not ch.isspace() and unicodedata.category(ch) != "Mn")
    return base / settings.thai_chars_per_sec


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
    """ดึงข้อความจากคำตอบโมเดล ซึ่งบางครั้งห่อมาเป็น {"text": ..} หรือ ["..."] แทนข้อความเปล่า"""
    if isinstance(item, dict):
        item = item.get("text") or item.get("th") or item.get("en") or ""
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
                   context: list[Utterance], title: str = "") -> tuple[str, str]:
    names = LANG_NAMES_EN if target == "en" else LANG_NAMES
    payload = {
        "title": title,
        "source_language": names.get(lang, lang),
        "previous_lines": [{"speaker": u.speaker, "text": u.target} for u in context],
        "sentences": [{"id": g[0].id, "speaker": g[0].speaker,
                       "parts": [{"seconds": round(u.duration, 1), "text": u.source} for u in g]}
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
                      title: str = "") -> None:
    pending = groups
    foreign: dict[int, list[str]] = {}  # คำตอบที่ครบแต่มีอักษรต้นฉบับปน ไว้ใช้เมื่อแปลใหม่แล้วยังไม่ผ่าน
    single = len(groups) == 1 and len(groups[0]) == 1
    for attempt in range(3 if single else 2):
        system, user = _groups_prompt(pending, lang, target, context, title)
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
        _translate_groups(pending[:mid], lang, target, context, title)
        _translate_groups(pending[mid:], lang, target, (context + done())[-6:], title)
    elif len(pending[0]) > 1:  # แบ่งท่อนให้ตรงไม่ได้ → แปลทีละท่อน
        for u in pending[0]:
            _translate_groups([[u]], lang, target, (context + done())[-6:], title)
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


# ---------------- ฟังก์ชันหลัก ----------------
def translate_utterances(utts: list[Utterance], lang: str, target: str = "th",
                         on_progress: Optional[Callable[[float], None]] = None,
                         check_cancel: Optional[Callable[[], None]] = None, title: str = "") -> None:
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
        _translate_groups(batch, lang, target, context, title)
        done += sum(map(len, batch))
        if on_progress:
            on_progress(done / len(utts))


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
    """ย่อบทที่คาดว่าพูดไม่ทันเวลา แม้จะเร่งความเร็วสูงสุดแล้ว"""
    if not settings.typhoon_api_key:
        return
    too_long = [u for u in utts
                if u.duration > 0 and estimate_seconds(u.target, target) > u.duration * max_speedup]
    for batch in _chunks(too_long, settings.translate_batch_size):
        shorten(batch, target)


def shorten(batch: list[Utterance], target: str = "th", target_ratio: float = 1.0) -> None:
    payload = [{"id": u.id, "seconds": round(u.duration * target_ratio, 1), "text": u.target} for u in batch]
    prompt = SHORTEN_PROMPT_EN if target == "en" else SHORTEN_PROMPT_TH
    try:
        result = _parse_json(_chat(prompt, json.dumps({"lines": payload}, ensure_ascii=False)))
        by_id = {int(x["id"]): _item_text(x) for x in result.get("lines", []) if "id" in x}
        for u in batch:
            if by_id.get(u.id) and not FOREIGN_SCRIPT.search(by_id[u.id]):
                u.target = by_id[u.id]
    except Exception as exc:  # noqa: BLE001  ย่อไม่ได้ก็ใช้บทเดิม แล้วไปเร่งความเร็วแทน
        log.warning("shorten failed: %s", exc)
