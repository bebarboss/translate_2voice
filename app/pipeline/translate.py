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
from pathlib import Path
from typing import Callable, Optional

from ..config import settings
from ..schemas import Utterance
from .pauses import tidy_marks
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
   ไม่แปลทีละคำ เรียงประโยคแบบไทย
   ห้ามเติมคำลงท้าย (นะ ครับ ค่ะ สิ ล่ะ เลย เถอะ หรอก จ้ะ) ใช้ได้เฉพาะคำถามที่ต้องมีคำแสดงคำถาม (ไหม เหรอ หรือ)
   เลี่ยงคำภาษาเขียนหรือภาษาทางการ เช่น ซึ่ง ดังนั้น อย่างไรก็ตาม กระผม ดิฉัน ท่าน(เมื่อไม่ใช่ยศ) ทำการ มีความ… เว้นแต่ตัวละครพูดแบบนั้นจริง
   ประโยคต้องเต็มแบบที่คนพูด ไม่ห้วนเป็นวลีโทรเลข และห้ามใช้คำย่อหรือตัวย่อ (ชม. กม. กก. รพ. กทม. ฯลฯ) ให้เขียนเต็มตามที่อ่านออกเสียง เช่น "สองชั่วโมง" เพราะนักพากย์อ่านตามตัวอักษร
   ตัวอย่าง: "I don't think that's a good idea." → "ฉันว่าไม่ดีมั้ง" ไม่ใช่ "ฉันไม่คิดว่านั่นเป็นความคิดที่ดี"
3. เลือกสรรพนามให้เข้ากับตัวละคร ความสัมพันธ์ และแนวเรื่อง และใช้ให้คงที่ตลอดเรื่อง ถ้ามี genre ให้ยึดตาม genre ไม่งั้นเดาจาก title
   เช่น ละครจีนโบราณ/กำลังภายใน ใช้ ข้า/เจ้า, ละครหรือหนังสมัยใหม่ ใช้ ฉัน/ผม/นาย/เธอ, การ์ตูนเด็ก ใช้ ฉัน/ผม/นาย/เธอ แบบเด็กพูดกัน ห้ามใช้ ข้า/เจ้า
   speaker คือชื่อตัวละครที่พูด (ถ้ารู้) ใช้เลือกสรรพนามให้เข้ากับคนพูด
4. คงอารมณ์ของต้นฉบับ (โกรธ เยาะเย้ย อ้อนวอน เศร้า ตกใจ) ด้วยการเลือกคำและคำอุทานที่ต้นฉบับมี และใส่เครื่องหมาย ! ? … ตามน้ำเสียง เพราะนักพากย์ใช้เครื่องหมายเหล่านี้กำหนดน้ำเสียง
5. แต่ละท่อนมี min_chars ถึง max_chars คือจำนวนตัวอักษรไทย (ไม่นับสระบน สระล่าง และวรรณยุกต์) ที่พูดได้เต็มเวลาที่ตัวละครพูดท่อนนั้นด้วยความเร็วปกติ
   ให้แปลยาวอยู่ในช่วงนี้ เสียงพากย์จะได้จบพร้อมกับที่ตัวละครหยุดขยับปาก ห้ามเกิน max_chars
   ถ้าแปลแล้วสั้นกว่า min_chars ให้แปลส่วนที่ต้นฉบับพูดให้ครบทุกคำ หรือเลือกคำพูดที่ยาวขึ้นแต่ความหมายเท่าเดิม ห้ามเติมคำลงท้าย ห้ามแต่งเนื้อหาใหม่
   ถ้ายาวเกิน max_chars ให้ตัดคำเสริมและคำซ้ำก่อน ห้ามตัดชื่อเฉพาะ ตัวเลข คำปฏิเสธ หรือคำถาม
6. ชื่อคนและสถานที่ ให้สะกดตามที่ใช้กันในฉบับภาษาไทยของเรื่องนั้น และเหมือนกันทุกครั้ง ถ้ามี glossary ให้ใช้คำแปลตาม glossary ทุกตัวอักษร
7. แต่ละ sentence คือคำพูดต่อเนื่องที่ถูกตัดเป็นท่อนตามเวลา (parts) ให้แปลทั้ง sentence ให้เป็นธรรมชาติ แล้วแบ่งคำแปลคืนเป็นท่อนตามลำดับเดิม จำนวนท่อนต้องเท่ากับ parts ของต้นฉบับพอดี และแต่ละท่อนต้องเป็นความหมายของท่อนต้นฉบับนั้นเท่านั้น ห้ามรวมท่อนหรือย้ายเนื้อหาไปท่อนอื่น เพราะเสียงพากย์แต่ละท่อนจะเล่นตรงเวลาที่ตัวละครพูดท่อนนั้น
8. ต้นฉบับบางท่อนมีเครื่องหมาย / คือจุดที่นักแสดงหยุดหายใจหรือเว้นจังหวะจริง ให้ใส่ / ในคำแปลของท่อนนั้นจำนวนเท่ากัน ตรงตำแหน่งที่ความหมายตรงกับต้นฉบับ (เสียงพากย์จะหยุดตรงนั้น) ห้ามใส่ / ในท่อนที่ต้นฉบับไม่มี และห้ามวาง / กลางคำหรือกลางชื่อ ถ้าตำแหน่งที่ตรงกันตกกลางคำ ให้วางที่ขอบคำที่ใกล้ที่สุด
9. register คือระดับภาษาของเรื่อง characters บอกว่าผู้พูดแต่ละคนเป็นใคร เพศ บทบาท แทนตัวเองและเรียกคนอื่นว่าอะไร ให้ใช้ตามนั้นทุกบรรทัด
   ท่อนที่มี likely_said แปลว่าบทถอดเสียงน่าจะผิด ถ้า text อ่านไม่เป็นความหรือชื่อผิด ให้แปลตามความหมายของ likely_said ถ้า text มีความหมายอยู่แล้วให้แปลตาม text
10. examples คือบทจากตอนก่อน ๆ ของเรื่องนี้ที่ผู้ใช้แก้เองแล้ว ให้ยึดสรรพนาม คำเรียก ชื่อ และสำนวนของแต่ละตัวละครตามนั้น (ไม่ต้องแปล examples)
   ท่อนที่มี previous_translation คือต้นฉบับประโยคเดียวกันที่เคยพากย์ไปแล้ว ให้ใช้คำแปลนั้นถ้าเข้ากับบริบท ปรับความยาวได้ตาม min_chars–max_chars
11. previous_lines และ next_lines คือบทก่อนหน้าและถัดไปของ sentences ไว้ดูบริบทให้ความหมาย สรรพนาม และน้ำเสียงต่อกันเท่านั้น ห้ามแปลซ้ำ ห้ามใส่ในคำตอบ และห้ามดึงเนื้อหาจากบทเหล่านั้นมาเติมใน sentences
   ถ้า content_type เป็น teaser บทข้างเคียงอาจเป็นคนละฉาก ห้ามตีความให้ต่อกัน
12. sentence ที่มี continuity_issue คือบทที่ผู้ตรวจพบว่าคำแปลเดิมความหมายไม่ต่อกับบทข้างเคียง ให้แปลใหม่แก้จุดนั้น โดยยังตรงกับต้นฉบับ
13. ตอบเป็น JSON อย่างเดียว ไม่มีคำอธิบาย"""

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
7. Some source parts contain "/": the points where the actor actually pauses or breathes. Put the same number of "/" in that part's translation, at the points that match the source meaning (the dub pauses there). Never add "/" to a part whose source has none, and never put "/" inside a word or name; use the nearest word boundary.
8. "previous_lines" and "next_lines" are the lines before and after "sentences", only so meaning, pronouns and tone connect. Never translate them again, never include them in your reply, and never pull their content into "sentences".
   When "content_type" is "teaser", neighbouring lines may come from other scenes; do not force them to connect.
9. A sentence with "continuity_issue" was found not to connect with its neighbours. Retranslate it to fix that, still matching the source.
10. Reply with JSON only, no explanations."""

SHORTEN_PROMPT_TH = """ย่อบทพากย์ภาษาไทยแต่ละบรรทัดให้ไม่เกิน max_chars ตัวอักษร (ไม่นับสระบน สระล่าง และวรรณยุกต์) เพื่อให้พูดจบทันใน seconds วินาทีด้วยความเร็วปกติ
ใจความสำคัญต้องครบและตรงเดิม ห้ามตัดชื่อคน ชื่อสถานที่ ชื่องานหรือองค์กร ตัวเลข คำปฏิเสธ และคำถาม คงอารมณ์ของตัวละคร ห้ามเปลี่ยนสรรพนามและชื่อเฉพาะ
ย่อด้วยการเรียบเรียงใหม่ให้สั้นแบบที่คนไทยพูดจริง (ตัดคำซ้ำ คำเสริม หรือส่วนที่ไม่สำคัญ) ผลต้องยังเป็นประโยคพูดที่ลื่นปาก ไม่ห้วนเป็นวลีโทรเลข ห้ามเติมคำลงท้าย (นะ ครับ ค่ะ สิ ล่ะ เลย)
ห้ามใช้คำย่อหรือตัวย่อ (ชม. กม. กก. รพ. ฯลฯ) ให้เขียนเต็มตามที่อ่านออกเสียง
ถ้าบทมีเครื่องหมาย / (จุดหยุดหายใจ) ให้คงไว้จำนวนเท่าเดิม ตรงตำแหน่งความหมายเดิม (ไม่นับเป็นตัวอักษร)
before และ after คือบทก่อนหน้าและถัดไป (ถ้ามี) ห้ามย่อหรือใส่ในคำตอบ ย่อแล้วความหมายต้องยังเชื่อมกับบทเหล่านั้น คงคำเชื่อมและสิ่งที่บทถัดไปตอบหรืออ้างถึง
ตอบเป็น JSON รูปแบบ {"lines":[{"id":1,"text":"..."}]} เท่านั้น"""

SHORTEN_PROMPT_EN = """Shorten each English dubbing line to at most "max_words" words so it can be spoken within its "seconds" value at a natural pace.
Keep the meaning and the character's emotion, and keep it natural spoken English. Never drop names (people, places, events, organizations), numbers, negations or questions.
Keep every "/" (a breathing pause) at the same point of meaning; it does not count as a word.
"before" and "after", when given, are the neighbouring lines: never shorten or return them. The shortened line must still connect with them, so keep linking words and whatever the next line answers or refers to.
Reply with JSON only, in the form {"lines":[{"id":1,"text":"..."}]}."""

EXPAND_PROMPT_TH = """บทพากย์ภาษาไทยบางบรรทัดสั้นกว่าเวลาที่ตัวละครพูดจริงมาก เสียงพากย์จบก่อนตัวละครหยุดขยับปาก
ขยายแต่ละบรรทัดให้ยาวประมาณ min_chars ถึง max_chars ตัวอักษร (ไม่นับสระบน สระล่าง และวรรณยุกต์) ให้พูดได้เต็ม seconds วินาที
กฎ:
1. ความหมายต้องตรงกับต้นฉบับ (source) ห้ามเพิ่มเนื้อหาที่ต้นฉบับไม่มี
2. ขยายด้วยสิ่งที่ต้นฉบับมีแต่คำแปลเดิมละไว้ หรือเลือกคำพูดที่ยาวขึ้นแต่ความหมายเท่าเดิม ห้ามเติมคำลงท้าย (นะ ครับ ค่ะ สิ ล่ะ เลย เนี่ย)
3. ใช้ภาษาพูดที่คนไทยพูดจริงแบบงานพากย์ ห้ามเปลี่ยนสรรพนามและชื่อเฉพาะ
4. ถ้าขยายแล้วฟังไม่เป็นธรรมชาติ ให้คืนบทเดิม
5. ถ้าบทมีเครื่องหมาย / (จุดหยุดหายใจ) ให้คงไว้จำนวนเท่าเดิม ตรงตำแหน่งความหมายเดิม
6. before และ after คือบทก่อนหน้าและถัดไป (ถ้ามี) ห้ามขยายหรือใส่ในคำตอบ และห้ามดึงเนื้อหาจากบทเหล่านั้นมาเติม บทที่ขยายแล้วต้องยังเชื่อมกับบทเหล่านั้น
ตอบเป็น JSON รูปแบบ {"lines":[{"id":1,"text":"..."}]} เท่านั้น"""

EXPAND_PROMPT_EN = """Some English dubbing lines are much shorter than the time the character actually speaks, so the dub ends while the mouth is still moving.
Expand each line to roughly "min_words" to "max_words" words so it fills its "seconds" value at a natural pace.
Keep the meaning of the original ("source"); never add content it does not have. First restore what the translation left out,
then use natural fillers, repetition or interjections that fit the character's emotion. If expanding would sound unnatural, return the line unchanged.
Keep every "/" (a breathing pause) at the same point of meaning.
"before" and "after", when given, are the neighbouring lines: never expand or return them, and never pull their content in. The expanded line must still connect with them.
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

SUSPECT_FIX_PROMPT_TH = """คุณซ่อมบทถอดเสียงภาษาไทยที่ระบบจับว่าเวลาหรือข้อความผิดปกติ
แต่ละบรรทัดมี text = บทถอดเสียง, seconds = ความยาวช่วงในคลิป, note = เหตุที่น่าสงสัย
กฎ:
1. แก้ให้เป็นประโยคพูดที่คนไทยพูดจริง ใจความครบตามที่น่าจะพูดจากข้อความเดิมและบริบท previous_lines / next_lines
2. ห้ามแต่งเรื่องใหม่ยาวเกินที่พูดได้ใน seconds ด้วยความเร็วปกติ (ประมาณ 11 ตัวอักษรไทย/วินาที ไม่นับวรรณยุกต์)
3. ถ้าข้อความขาดกลางคำ ให้เติมให้จบคำ/ประโยคอย่างสั้นที่สุดที่เข้ากับบริบท
4. ห้ามใส่คำลงท้ายเกินจำเป็น (นะ ครับ ค่ะ) เว้นต้นฉบับมีอยู่แล้ว
5. ตอบ JSON เท่านั้น {"lines":[{"id":1,"text":"..."}]} ครบทุก id"""

SUSPECT_FIX_PROMPT_EN = """You repair automatic speech-transcript lines flagged as timing/text anomalies.
Each line has text, seconds (clip span), and note.
Rules:
1. Fix into natural spoken English that matches what the broken transcript likely meant, using previous_lines/next_lines for context.
2. Keep length speakable within seconds at a normal pace (~2.5 words/sec). Do not invent a long new plot.
3. If a word is cut mid-way, complete it briefly.
4. Reply JSON only: {"lines":[{"id":1,"text":"..."}]} for every id."""

DUB_JUDGE_PROMPT = """คุณเป็นผู้ตรวจคุณภาพเสียงพากย์อัตโนมัติ
แต่ละบรรทัดมี: id, target (บทที่ต้องพูด), heard (สิ่งที่ระบบถอดจากเสียงพากย์), score (0–1 ความตรงบท), seconds (เวลาที่มี)
เลือก action อย่างเดียวต่อบรรทัด:
- retry = พากย์ใหม่ด้วยบทเดิม (เสียงเพี้ยน/มั่ว แต่บทโอเค)
- shorten = บทยาวเกินเวลาหรือพูดไม่ทัน → ย่อบทแล้วพากย์ใหม่
- accept = รับได้ หรือ score พอใช้แล้ว ไม่ต้องทำอะไร (อาจยังติดป้ายให้คนฟัง)
กฎ: ถ้า heard ว่างหรือคนละเรื่องจาก target ชัด ๆ ใช้ retry; ถ้า target ยาวเกิน seconds ชัด ๆ ใช้ shorten; ไม่แน่ใจใช้ retry ก่อน accept
ตอบ JSON เท่านั้น {"lines":[{"id":1,"action":"retry"}]} ครบทุก id"""

NATURALIZE_PROMPT_TH = """คุณปรับบทพากย์ไทยให้ออกเสียงเป็นธรรมชาติเหมือนบทละคร/ซีรีส์
แต่ละบรรทัดมี source (ต้นฉบับ), text (คำแปลปัจจุบัน), seconds (เวลาพูดที่มี), speaker
กฎ:
1. รักษาใจความ ชื่อคน และข้อเท็จจริงตาม source/text ห้ามแต่งเรื่องใหม่
2. ใช้ภาษาพูดไทยที่ตัวละครพูดจริง (สรรพนาม คำลงท้าย ระดับภาษาตามสถานะ) ไม่ใช่แปลตรงตัวแข็ง ๆ
3. ความยาวต้องพูดได้ใน seconds (ราว 11 ตัวอักษรไทย/วินาที ไม่นับวรรณยุกต์) ไม่ยาวเกิน text เดิมเกิน ~20%
4. บรรทัดที่ฟังเป็นธรรมชาติอยู่แล้ว คืน text เดิม
5. ตอบ JSON เท่านั้น {"lines":[{"id":1,"text":"..."}]} ครบทุก id"""

NATURALIZE_PROMPT_EN = """You rewrite dubbed English dialogue so it sounds like natural spoken drama.
Each line has source, text (current translation), seconds, speaker.
Rules:
1. Keep meaning, names and facts from source/text. Do not invent plot.
2. Prefer natural spoken English for the character, not stiff literal translation.
3. Keep speakable within seconds (~2.5 words/sec). Do not grow more than ~20% vs text.
4. If already natural, return text unchanged.
5. Reply JSON only: {"lines":[{"id":1,"text":"..."}]} for every id."""

MOOD_PROMPT_TH = """คุณคือผู้กำกับการพากย์ เลือกอารมณ์ของเสียงพากย์ให้แต่ละบรรทัด จากบทต้นฉบับ (source) บทพากย์ (text) และบรรทัดรอบ ๆ
แต่ละบรรทัดมี moods คืออารมณ์ที่เลือกได้ และ excite คือความตื่นเต้นที่วัดจากเสียงต้นฉบับ (0 = ปกติของตัวละครนั้น, บวก = ดัง/ตื่นเต้นกว่าปกติ, ลบ = เบา/เนิบกว่าปกติ) ถ้ามี
ความหมายของอารมณ์: angry = โกรธ ตะโกน ดุ, sad = เศร้า ร้องไห้ ผิดหวัง, happy = ดีใจ ตื่นเต้น หัวเราะ, whisper = กระซิบ พูดเบา ๆ แอบพูด, scared = ตกใจ กลัว ตื่นตระหนก
กฎ:
1. ตอบ normal เมื่อเป็นบทพูดทั่วไปหรือไม่แน่ใจ เลือกอารมณ์อื่นเฉพาะเมื่อบทและน้ำเสียงชัดเจน เพราะเสียงอารมณ์ที่ผิดฟังแย่กว่าเสียงปกติ
2. เลือกได้เฉพาะ normal หรืออารมณ์ใน moods ของบรรทัดนั้น
3. ตอบเป็น JSON รูปแบบ {"lines":[{"id":1,"mood":"normal"}]} ครบทุก id เท่านั้น"""

CONTINUITY_PROMPT = """คุณคือผู้ตรวจบทพากย์ของเรื่องที่เล่าต่อเนื่อง lines คือบทที่ต้องตรวจตามลำดับเวลา (source = ต้นฉบับ, text = คำแปล) previous_lines คือบทก่อนหน้า ไว้ดูบริบท ไม่ต้องตรวจ
หาบรรทัดที่คำแปลความหมายไม่ต่อกับบรรทัดก่อนหรือหลัง เช่น คำตอบไม่ตรงคำถาม ท่อนถัดไปไม่รับกับท่อนก่อน สรรพนามหรือคนที่ถูกเรียกสลับ เนื้อหาย้ายไปผิดท่อน
กฎ:
1. เทียบกับ source เสมอ ถ้าต้นฉบับก็ไม่ต่อกันตรงนั้น (ถอดเสียงขาด เปลี่ยนฉาก) ไม่นับ
2. ไม่นับเรื่องสำนวน ความไพเราะ หรือความยาว ไม่แน่ใจไม่ต้องใส่
ตอบเป็น JSON รูปแบบ {"breaks":[{"id":1,"note":"เหตุผลสั้น ๆ ภาษาไทย"}]} ไม่มีให้ตอบ {"breaks":[]}"""

TERMS_PROMPT = """คุณคือผู้ตรวจบทพากย์ของคลิปทีเซอร์หรือคลิปรวมฉาก บทแต่ละช่วงอาจเป็นคนละฉาก ไม่ต้องตรวจว่าเรื่องต่อกันไหม
ตรวจอย่างเดียวว่าชื่อคนและศัพท์เฉพาะในคำแปล (text) ตรงกันทุกบรรทัด และตรงกับ glossary และ names (ถ้ามี) เช่น ชื่อเดียวกันแต่สะกดต่างกัน หรือต้นฉบับ (source) มีชื่อแต่คำแปลใช้ชื่ออื่น
ไม่นับสำนวน สรรพนาม หรือความยาว ไม่แน่ใจไม่ต้องใส่ ห้ามเสนอคำแปลใหม่ทั้งบรรทัด
ตอบเป็น JSON รูปแบบ {"issues":[{"id":1,"note":"ชื่อหรือศัพท์ที่ไม่ตรงกัน สั้น ๆ ภาษาไทย"}]} ไม่มีให้ตอบ {"issues":[]}"""

CONTEXT_BEFORE, CONTEXT_AFTER = 3, 2  # จำนวนประโยคข้างเคียงที่ส่งไปดูบริบทตอนแปล
REVIEW_ROUNDS = 2  # แปลใหม่ได้ไม่เกินกี่รอบในขั้นตรวจความต่อเนื่อง
TERMS_BATCH_SIZE = 60  # ตรวจชื่อต้องเห็นหลายบรรทัดพร้อมกันถึงจะเทียบตัวสะกดได้

_client = None
_local = None


# ---------------- ตัวช่วย ----------------
def estimate_seconds(text: str, target_lang: str = "th") -> float:
    """ประมาณเวลาพูด: ภาษาไทยนับตัวอักษรที่ไม่ใช่สระบนล่างและวรรณยุกต์ ภาษาอังกฤษนับคำ"""
    if target_lang == "en":
        return len([t for t in text.split() if t != "/"]) / settings.en_words_per_sec
    base = sum(1 for ch in text if not ch.isspace() and ch != "/" and unicodedata.category(ch) != "Mn")
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


def _with_order(utts: list[Utterance], hints: Optional[dict]) -> dict:
    """เติมเวลาที่มีและลำดับประโยคทั้งเรื่องลง hints ใช้หาประโยคข้างเคียงของแต่ละชุด"""
    groups = _group_lines(utts)
    return {**(hints or {}), "budgets": budgets(utts), "sentences": groups,
            "sentence_at": {u.id: i for i, g in enumerate(groups) for u in g}}


def _neighbours(groups: list[list[Utterance]], hints: dict) -> tuple[list[list[Utterance]], list[list[Utterance]]]:
    """ประโยคก่อนหน้าและถัดไปของชุดนี้ ไม่รวมบรรทัดที่กำลังแปล
    ชุดที่ถูกแบ่งเป็นทีละท่อน ท่อนอื่นของประโยคเดียวกันนับเป็นข้างเคียงด้วย"""
    order, at = hints["sentences"], hints["sentence_at"]
    first, last = groups[0][0], groups[-1][-1]
    i, j = at[first.id], at[last.id]
    head = [u for u in order[i] if u.start < first.start]
    tail = [u for u in order[j] if u.start > last.start]
    return (order[max(0, i - CONTEXT_BEFORE):i] + ([head] if head else []),
            ([tail] if tail else []) + order[j + 1:j + 1 + CONTEXT_AFTER])


CONTEXT_NOTE_TH = "บริบท ห้ามแปล"
CONTEXT_NOTE_EN = "context only, do not translate"


def _sentence_brief(g: list[Utterance], hints: dict, with_text: bool = True) -> dict:
    """with_text: ใส่คำแปลที่ได้แล้วด้วย (บทก่อนหน้า) บทถัดไปส่งแต่ต้นฉบับ"""
    text = " ".join(u.target for u in g if u.target) if with_text else ""
    return {"speaker": _speaker_label(g[0].speaker, hints), "source": " ".join(u.source for u in g),
            **({"text": text} if text else {})}


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
    examples, fixed = [], {}
    if hints.get("memory"):
        from ..memory import examples_for
        examples, fixed = examples_for(hints["memory"], [u for g in groups for u in g], hints.get("char_of") or {})
    if settings.translate_neighbors and hints.get("sentences"):
        before, after = _neighbours(groups, hints)
        note = CONTEXT_NOTE_EN if target == "en" else CONTEXT_NOTE_TH
        around = {"previous_lines_note": note,
                  "previous_lines": [_sentence_brief(g, hints) for g in before],
                  "next_lines_note": note,
                  "next_lines": [_sentence_brief(g, hints, with_text=False) for g in after]}
    else:
        around = {"previous_lines": [{"speaker": _speaker_label(u.speaker, hints), "text": u.target} for u in context]}
    issues = hints.get("issues") or {}
    payload = {
        "title": title,
        **({"content_type": hints["content_type"]} if hints.get("content_type") else {}),
        **({"examples": examples} if examples else {}),
        **({"genre": hints["genre"]} if hints.get("genre") else {}),
        **({"glossary": glossary} if glossary else {}),
        **({"register": hints["register"]} if hints.get("register") else {}),
        **({"characters": {_speaker_label(sp, hints): info for sp, info in hints["characters"].items()
                           if any(sp == g[0].speaker for g in groups)}} if hints.get("characters") else {}),
        "source_language": names.get(lang, lang),
        **around,
        "sentences": [{"id": g[0].id, "speaker": _speaker_label(g[0].speaker, hints),
                       **({"continuity_issue": issues[g[0].id]} if g[0].id in issues else {}),
                       "parts": [{"seconds": round(budget.get(u.id, u.duration), 1),
                                  # ขั้นต่ำ 80% ของเวลาที่ตัวละครพูดจริง (ไม่นับช่วงเงียบท้ายประโยค) ให้เสียงพากย์จบพร้อมปาก
                                  lo_key: max(1, int(max_length(u.duration, target) * 0.8)) if u.duration >= 1.0 else 1,
                                  limit_key: max_length(budget.get(u.id, u.duration), target),
                                  "text": (hints.get("marked") or {}).get(u.id, u.source),
                                  **({"likely_said": hints["asr_fixes"][u.id]} if u.id in (hints.get("asr_fixes") or {}) else {}),
                                  **({"previous_translation": fixed[u.id]} if u.id in fixed else {})}
                                 for u in g]}
                      for g in groups],
    }
    if target == "en":
        return SYSTEM_PROMPT_EN, (
            "Translate the sentences in \"sentences\" into English (\"title\" is the video title, \"previous_lines\" and \"next_lines\" "
            "are the lines around them, all for context only, do not translate or return them). Give exactly one translated part per source part.\n"
            'Reply as {"sentences":[{"id":1,"parts":["part 1","part 2"]}]}\n\n'
            + json.dumps(payload, ensure_ascii=False))
    return SYSTEM_PROMPT_TH, (
        "แปล sentences เป็นภาษาไทย (title คือชื่อคลิป previous_lines และ next_lines คือบทก่อนหน้าและถัดไป ไว้ดูบริบท ห้ามแปลซ้ำหรือใส่ในคำตอบ) "
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
                    u.target = tidy_marks(text)
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
        _translate_plain(pending[0][0], lang, target, context, foreign.get(pending[0][0].id), hints)


def _translate_plain(u: Utterance, lang: str, target: str, context: list[Utterance],
                     foreign: Optional[list[str]] = None, hints: Optional[dict] = None) -> None:
    """ทางสุดท้ายของประโยคเดียวที่แปลแบบ JSON ไม่ผ่าน: ขอคำแปลเป็นข้อความเปล่า ไม่ต้องจัดรูปแบบ
    ถ้ายังไม่ได้ ใช้คำตอบที่ตัดอักษรต้นฉบับทิ้ง หรือปล่อยว่างให้ผู้ใช้แก้ในหน้าตรวจบท ดีกว่าให้ทั้งงานล้ม"""
    names = LANG_NAMES_EN if target == "en" else LANG_NAMES
    before, after = " / ".join(x.target for x in context[-3:]), ""
    if settings.translate_neighbors and (hints or {}).get("sentences"):
        near = _neighbours([[u]], hints)
        before = " / ".join(x.target or x.source for g in near[0] for x in g)
        after = " / ".join(x.source for g in near[1] for x in g)
    if target == "en":
        system = SYSTEM_PROMPT_EN
        user = (f"Earlier lines (context only): {before}\n"
                + (f"Next lines (context only, do not translate): {after}\n" if after else "") +
                f"Translate this {names.get(lang, lang)} line into English. Reply with the translation only.\n{u.source}")
    else:
        system = SYSTEM_PROMPT_TH
        user = (f"บทก่อนหน้า (ไว้ดูบริบท): {before}\n"
                + (f"บทถัดไป (ไว้ดูบริบท ห้ามแปล): {after}\n" if after else "") +
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


def same_lang(lang: str, target: str) -> bool:
    """ภาษาต้นทาง = ปลายทาง (เทียบ 2 ตัวอักษรแรก เช่น th / th-TH)"""
    a, b = (lang or "").strip().lower()[:2], (target or "").strip().lower()[:2]
    return bool(a) and a == b


def ensure_same_lang_targets(utts: list[Utterance], lang: str, target: str = "th") -> int:
    """ภาษาเดียวกัน: เติม target จาก source ทันที (ไม่รอ API) คืนจำนวนบรรทัดที่เติม"""
    if not same_lang(lang, target):
        return 0
    n = 0
    for u in utts:
        src = (u.source or "").strip()
        if src and not (u.target or "").strip():
            u.target = src
            n += 1
    if n:
        log.info("same-lang: copied source → target on %d empty lines", n)
    return n


# ---------------- ฟังก์ชันหลัก ----------------
def translate_utterances(utts: list[Utterance], lang: str, target: str = "th",
                         on_progress: Optional[Callable[[float], None]] = None,
                         check_cancel: Optional[Callable[[], None]] = None, title: str = "",
                         hints: Optional[dict] = None) -> None:
    """hints: genre (แนวเรื่อง), glossary (ชื่อเฉพาะ บรรทัดละคำ เช่น ドラえもん = โดราเอมอน), names (ผู้พูด → ชื่อตัวละคร)"""
    hints = _with_order(utts, hints)
    if same_lang(lang, target):
        ensure_same_lang_targets(utts, lang, target)
        # บังคับให้ทุกท่อนที่มีต้นฉบับมีบทพากย์ (กัน target เป็นช่องว่าง)
        for u in utts:
            if (u.source or "").strip() and not (u.target or "").strip():
                u.target = u.source
        if settings.typhoon_api_key and not settings.mock_pipeline:
            proofread(utts, target, on_progress, check_cancel, title)
            # proofread ห้ามเหลือบทว่าง
            ensure_same_lang_targets(utts, lang, target)
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
    for batch in _group_batches(hints["sentences"], settings.translate_batch_size):
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



# ---------------------------------------------------------------- วิเคราะห์เรื่องก่อนแปล
STORY_PROMPT = """คุณคือผู้กำกับบทพากย์ อ่านบทต้นฉบับทั้งเรื่อง (ถอดจากเสียงอัตโนมัติ อาจมีคำผิด) แล้ววิเคราะห์ให้ผู้แปลใช้
บอกสิ่งที่บทและชื่อคลิปบ่งชี้เท่านั้น ห้ามแต่งข้อมูลที่ไม่มีหลักฐาน ถ้าไม่แน่ใจให้เว้นว่าง
- genre: แนวเรื่องสั้น ๆ เช่น ซีรีส์เกาหลีราชสำนักแฟนตาซี, หนังแอ็กชันจากเกมต่อสู้, การ์ตูนเด็ก
- setting: ยุคและสถานที่ของเรื่อง สั้น ๆ
- register: ระดับภาษาและสรรพนามที่ควรใช้ในภาษาปลายทาง (เช่น ราชาศัพท์ หม่อมฉัน/เพคะ/ฝ่าบาท, ภาษาพูดสมัยใหม่ ฉัน/นาย)
- characters: ผู้พูดแต่ละคน (speaker ตามที่ให้มา) speaker เดียวกันอาจเป็นคนละคนเพราะระบบแยกเสียงผิดได้ ให้บอกคนที่พูดมากที่สุด
  name = ชื่อตัวละครอย่างเดียวเป็นภาษาปลายทางตามที่ใช้กันในฉบับแปลของเรื่องนั้น ไม่ใส่วงเล็บหรือบทบาท (ไม่รู้ชื่อให้ใช้บทบาท เช่น ผู้บรรยาย, จักรพรรดิ)
  gender = male / female / unknown, role = บทบาทและความสัมพันธ์กับคนอื่นสั้น ๆ
  self = สรรพนามแทนตัวเอง, addresses = เรียกคนอื่นว่าอะไร (ภาษาปลายทาง)
- glossary: เฉพาะชื่อเฉพาะ (คน สถานที่ ชื่อเรื่อง ท่าไม้ตาย องค์กร) เป็น "ต้นฉบับ = ภาษาปลายทาง" สะกดตามฉบับแปลที่ใช้กันจริง
  ไม่ใส่คำทั่วไป (หย่า แต่งงาน ฝ่าบาท) ไม่ใส่วงเล็บหรือคำอธิบาย หนึ่งชื่อหนึ่งบรรทัด
  ถ้าบทถอดผิดจากชื่อจริง ให้ใส่ชื่อที่ถูก (เช่น ได้ยิน Kyle แต่ในเรื่องคือ Guile → Guile = กายล์)
- asr_fixes: เฉพาะบรรทัดที่ถอดเสียงผิดจนอ่านไม่เป็นความ ชื่อผิด หรือคำถูกตัดกลางคำ {"id": เลขบรรทัด, "likely": "ต้นฉบับที่น่าจะพูดจริง"}
  บรรทัดที่อ่านแล้วมีความหมายอยู่แล้ว ห้ามเปลี่ยนคำให้เข้ากับที่คิดว่าควรเป็น
- speaker_doubts: บรรทัดที่เนื้อหาไม่น่าใช่คนที่ระบบบอก {"id": เลขบรรทัด, "speaker": "ผู้พูดที่น่าจะพูดจริง (จากรายชื่อ speaker ที่ให้มา ไม่แน่ใจให้เว้นว่าง)", "note": "เหตุผลสั้น ๆ"}
  ใส่เฉพาะบรรทัดที่คิดว่าผิดจริง ห้ามใส่บรรทัดที่ speaker ถูกอยู่แล้ว
ตอบเป็น JSON อย่างเดียว"""

CONTENT_TYPE_RULE = """
- content_type: continuous = เรื่องเดียวเล่าต่อเนื่อง บทแต่ละช่วงต่อกัน เช่น ตอนของละคร หนัง การ์ตูน
  teaser = ทีเซอร์ ตัวอย่าง หรือคลิปรวมฉาก ตัดฉากสั้น ๆ มาเรียงกันจนบทไม่จำเป็นต้องต่อกัน ตอบค่าเดียว ไม่แน่ใจให้เว้นว่าง"""
CONTENT_TYPES = ("continuous", "teaser")


def _story_lines(utts: list[Utterance]) -> list[dict]:
    return [{"id": u.id, "speaker": u.speaker, "t": round(u.start, 1), "text": u.source} for u in utts if u.source.strip()]


def analyze_story(utts: list[Utterance], lang: str, target: str = "th", title: str = "",
                  hints: Optional[dict] = None, max_chars: int = 24000) -> dict:
    """อ่านบทต้นฉบับทั้งเรื่องแล้วสรุปแนวเรื่อง ระดับภาษา ตัวละคร ชื่อเฉพาะ จุดที่ถอดเสียงน่าจะผิด และผู้พูดที่น่าสงสัย
    hints: แนวเรื่อง ชื่อเฉพาะ และชื่อตัวละครที่ผู้ใช้ตั้งไว้ (ถือเป็นข้อเท็จจริง) บทยาวเกิน max_chars อ่านเป็นช่วงแล้วต่อยอดผลเดิม"""
    hints = hints or {}
    names = LANG_NAMES_EN if target == "en" else LANG_NAMES
    lines = _story_lines(utts)
    chunks, cur, size = [], [], 0
    for x in lines:
        n = len(x["text"]) + 30
        if cur and size + n > max_chars:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(x)
        size += n
    if cur:
        chunks.append(cur)
    result: dict = {}
    for part in chunks:
        payload = {
            "title": title, "source_language": names.get(lang, lang), "target_language": names.get(target, target),
            **({"user_genre": hints["genre"]} if hints.get("genre") else {}),
            **({"user_glossary": _glossary(hints)} if _glossary(hints) else {}),
            **({"user_names": hints["names"]} if hints.get("names") else {}),
            **({"previous_analysis": result} if result else {}),
            "lines": part,
        }
        reply = _chat(STORY_PROMPT + (CONTENT_TYPE_RULE if settings.story_content_type else ""), (
            "วิเคราะห์บทนี้ (user_* คือข้อมูลที่ผู้ใช้ตั้งไว้ ให้ยึดตามนั้น previous_analysis คือผลจากช่วงก่อนหน้า ให้ต่อยอดและตอบผลรวมทั้งหมด)\n"
            'ตอบรูปแบบ {' + ('"content_type":"",' if settings.story_content_type else "") + '"genre":"","setting":"","register":"","characters":[{"speaker":"speaker_01","name":"","gender":"",'
            '"role":"","self":"","addresses":""}],"glossary":["ต้นฉบับ = ปลายทาง"],"asr_fixes":[{"id":1,"likely":""}],'
            '"speaker_doubts":[{"id":1,"speaker":"","note":""}]}\n\n' + json.dumps(payload, ensure_ascii=False)),
            temperature=0.2, max_tokens=4096)
        data = _parse_json(reply)
        if isinstance(data, dict) and data:
            result = data
    return clean_story(result, {u.speaker for u in utts}, {u.id for u in utts}, {u.id: u.speaker for u in utts})


def clean_story(data: dict, speakers: set[str], ids: set[int], speaker_of: Optional[dict[int, str]] = None) -> dict:
    """ตัดค่าที่ผิดรูปแบบ และผู้พูดหรือบรรทัดที่ไม่มีในงาน (กันโมเดลตอบมั่ว)
    speaker_of: id บรรทัด → ผู้พูดตอนนี้ ข้อสงสัยที่เสนอผู้พูดคนเดิมตัดทิ้ง (โมเดลมักใส่บรรทัดที่ถูกอยู่แล้ว)"""
    s = lambda v, n=200: str(v or "").strip()[:n]  # noqa: E731
    chars = []
    for c in data.get("characters") or []:
        if isinstance(c, dict) and c.get("speaker") in speakers:
            g = s(c.get("gender"), 10).lower()
            chars.append({"speaker": c["speaker"], "name": re.sub(r"\s*[(（].*?[)）]\s*", " ", s(c.get("name"), 60)).strip(), "gender": g if g in ("male", "female") else "",
                          "role": s(c.get("role")), "self": s(c.get("self"), 40), "addresses": s(c.get("addresses"), 120)})
    gloss = [re.sub(r"\s*[(（].*?[)）]", "", s(x, 120)).strip() for x in data.get("glossary") or [] if isinstance(x, str) and "=" in x][:60]
    pick = lambda key, field: [{"id": int(x["id"]), field: s(x.get(field), 300)} for x in data.get(key) or []  # noqa: E731
                               if isinstance(x, dict) and str(x.get("id", "")).lstrip("-").isdigit() and int(x["id"]) in ids
                               and s(x.get(field))]
    doubts = []
    for x in data.get("speaker_doubts") or []:
        if not (isinstance(x, dict) and str(x.get("id", "")).lstrip("-").isdigit() and int(x["id"]) in ids and s(x.get("note"))):
            continue
        sp = s(x.get("speaker"), 40) if x.get("speaker") in speakers else ""
        if not (sp and speaker_of and speaker_of.get(int(x["id"])) == sp):
            doubts.append({"id": int(x["id"]), "speaker": sp, "note": s(x.get("note"), 300)})
    kind = s(data.get("content_type"), 20).lower()
    return {"content_type": kind if kind in CONTENT_TYPES else "",
            "genre": s(data.get("genre"), 120), "setting": s(data.get("setting")), "register": s(data.get("register"), 400),
            "characters": chars, "glossary": gloss, "asr_fixes": pick("asr_fixes", "likely")[:40],
            "speaker_doubts": doubts[:40]}


def story_hints(story: Optional[dict], hints: dict) -> dict:
    """รวมผลวิเคราะห์เรื่องเข้ากับสิ่งที่ผู้ใช้ตั้งไว้ ของผู้ใช้มาก่อนเสมอ"""
    if not story:
        return hints
    out = dict(hints)
    if not out.get("genre"):
        out["genre"] = " · ".join(x for x in (story.get("genre"), story.get("setting")) if x)
    user = _glossary(hints)
    known = {line.split("=")[0].strip().lower() for line in user}
    out["glossary"] = "\n".join(user + [g for g in story.get("glossary") or [] if g.split("=")[0].strip().lower() not in known])
    names = dict(hints.get("names") or {})
    for c in story.get("characters") or []:
        if c.get("name") and not names.get(c["speaker"]):
            names[c["speaker"]] = c["name"]
    out["names"] = names
    out["register"] = story.get("register") or ""
    out["content_type"] = story.get("content_type", "") if settings.story_content_type else ""
    out["characters"] = {c["speaker"]: {k: c[k] for k in ("gender", "role", "self", "addresses") if c.get(k)}
                         for c in story.get("characters") or []}
    out["asr_fixes"] = {x["id"]: x["likely"] for x in story.get("asr_fixes") or []}
    return out

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


def fix_suspect_sources(utts: list[Utterance], lang: str = "th", title: str = "",
                        check_cancel: Optional[Callable[[], None]] = None) -> int:
    """ให้โมเดลซ่อมเฉพาะท่อนที่ gate ติดป้ายน่าสงสัย (แก้ source และ target ว่าง/เดิม)
    คืนจำนวนบรรทัดที่เปลี่ยน"""
    if not settings.ai_fix_suspects or not settings.typhoon_api_key or settings.mock_pipeline:
        return 0
    bad = [u for u in utts if u.unclear or (u.check_note and "น่าสงสัย" in u.check_note)]
    if not bad:
        return 0
    prompt = SUSPECT_FIX_PROMPT_EN if lang == "en" else SUSPECT_FIX_PROMPT_TH
    order = sorted(utts, key=lambda u: u.start)
    at = {u.id: i for i, u in enumerate(order)}
    changed = 0
    for batch in _chunks(bad, min(12, settings.translate_batch_size)):
        if check_cancel:
            check_cancel()
        lines = []
        for u in batch:
            i = at[u.id]
            item = {"id": u.id, "speaker": u.speaker, "seconds": round(u.duration, 1),
                    "text": u.source, "note": u.check_note or "suspect"}
            if i > 0:
                item["previous_lines"] = [{"speaker": order[i - 1].speaker, "text": order[i - 1].source}]
            if i + 1 < len(order):
                item["next_lines"] = [{"speaker": order[i + 1].speaker, "text": order[i + 1].source}]
            lines.append(item)
        payload = {"title": title, "lines": lines}
        try:
            head = f"title: {title}\n\n" if title else ""
            result = _parse_json(_chat(prompt, head + json.dumps(payload, ensure_ascii=False), temperature=0.2,
                                       max_tokens=min(4096, 300 + 120 * len(batch))))
            by_id = {int(x["id"]): _item_text(x) for x in result.get("lines", []) if "id" in x}
        except Exception as exc:  # noqa: BLE001
            log.warning("fix_suspect_sources failed: %s", exc)
            continue
        for u in batch:
            text = by_id.get(u.id)
            if not text or FOREIGN_SCRIPT.search(text):
                continue
            # ยอมให้ยาวขึ้นเพื่อเติมคำที่ขาด แต่ไม่ให้ยาวทะลุเวลาพูดมาก
            lo, hi = 0.4, 2.5
            ratio = len(text) / max(len(u.source), 1)
            if not (lo <= ratio <= hi):
                continue
            if estimate_seconds(text, "en" if lang == "en" else "th") > max(u.duration, 0.5) * 1.4:
                continue
            if text.strip() != u.source.strip():
                same_target = (u.target or "").strip() in ("", u.source.strip())
                u.source = text.strip()
                if same_target:
                    u.target = spoken(u.source) if lang == "th" else u.source
                u.unclear = False
                if u.check_note and "น่าสงสัย" in u.check_note:
                    u.check_note = ""
                changed += 1
    if changed:
        log.info("AI fixed %d suspect source lines", changed)
    return changed


def naturalize_dialogue(utts: list[Utterance], target: str = "th",
                        check_cancel: Optional[Callable[[], None]] = None) -> int:
    """ปรับบทพากย์ให้ออกเสียงเป็นธรรมชาติหลังแปล/ย่อ คืนจำนวนบรรทัดที่เปลี่ยน"""
    if (not settings.ai_naturalize or not settings.typhoon_api_key or settings.mock_pipeline
            or target not in ("th", "en")):
        return 0
    lines = [u for u in utts if (u.target or "").strip()]
    if not lines:
        return 0
    prompt = NATURALIZE_PROMPT_TH if target == "th" else NATURALIZE_PROMPT_EN
    changed = 0
    for batch in _chunks(lines, min(16, settings.translate_batch_size)):
        if check_cancel:
            check_cancel()
        payload = {"lines": [{"id": u.id, "speaker": u.speaker, "seconds": round(u.duration, 1),
                              "source": u.source, "text": u.target} for u in batch]}
        try:
            result = _parse_json(_chat(prompt, json.dumps(payload, ensure_ascii=False), temperature=0.3,
                                       max_tokens=min(4096, 300 + 120 * len(batch))))
            by_id = {int(x["id"]): _item_text(x) for x in result.get("lines", []) if "id" in x}
        except Exception as exc:  # noqa: BLE001
            log.warning("naturalize_dialogue failed: %s", exc)
            continue
        for u in batch:
            text = by_id.get(u.id)
            if not text or FOREIGN_SCRIPT.search(text):
                continue
            text = spoken(text) if target == "th" else text.strip()
            old = (u.target or "").strip()
            if not text or text == old:
                continue
            # คงจังหวะปาก: ไม่ยาวเกินเวลา×fit_tolerance และไม่หดจนเสียใจความ
            if estimate_seconds(text, target) > max(u.duration, 0.5) * settings.fit_tolerance:
                continue
            if len(text) < max(2, int(len(old) * 0.45)):
                continue
            if estimate_seconds(text, target) < u.duration * settings.fit_min_ratio and u.duration >= 1.0:
                # สั้นกว่าเกณฑ์ขยาย — อย่าทำให้แย่กว่าบทเดิม
                if estimate_seconds(text, target) < estimate_seconds(old, target):
                    continue
            u.target = text
            changed += 1
    if changed:
        log.info("naturalized %d dialogue lines", changed)
    return changed


def fill_empty_targets(utts: list[Utterance], lang: str, target: str = "th", title: str = "",
                       hints: Optional[dict] = None, job_dir: Optional[Path] = None,
                       check_cancel: Optional[Callable[[], None]] = None) -> int:
    """เติมบทพากย์ที่ว่างก่อนพากย์: same-lang คัดลอกทันที → กู้ ai_targets → AI แปล
    คืนจำนวนบรรทัดที่เติมได้ (ลดท่อนเงียบตอนตัด vocals ต้นฉบับออก)"""
    # ภาษาเดียวกันไม่ต้องพึ่ง API / ธง AI_FILL_EMPTY
    filled = ensure_same_lang_targets(utts, lang, target)
    if settings.mock_pipeline:
        return filled
    empty = [u for u in utts if not (u.target or "").strip() and (u.source or "").strip()]
    if not empty:
        return filled
    if not settings.ai_fill_empty:
        if filled:
            log.info("filled %d empty targets (same-lang only; AI_FILL_EMPTY off)", filled)
        return filled
    ai: dict[int, str] = {}
    if job_dir is not None:
        try:
            raw = json.loads((Path(job_dir) / "ai_targets.json").read_text(encoding="utf-8"))
            ai = {int(k): str(v) for k, v in raw.items() if v}
        except (OSError, ValueError, TypeError):
            ai = {}
    still: list[Utterance] = []
    for u in empty:
        prev = (ai.get(u.id) or "").strip()
        if prev and not FOREIGN_SCRIPT.search(prev):
            u.target = spoken(prev) if target == "th" else prev
            filled += 1
        else:
            still.append(u)
    if not still:
        if filled:
            log.info("filled %d empty targets from same-lang/ai_targets", filled)
        return filled
    if not settings.typhoon_api_key:
        log.warning("empty targets remain %s (no API key to fill)", [u.id for u in still])
        return filled
    hints = _with_order(utts, hints)
    order = sorted(utts, key=lambda u: u.start)
    for u in still:
        if check_cancel:
            check_cancel()
        if same_lang(lang, target):
            u.target = u.source
        else:
            context = [x for x in order if x.target.strip() and x.start < u.start][-6:]
            before = u.target
            try:
                _translate_groups([[u]], lang, target, context, title, hints)
            except Exception as exc:  # noqa: BLE001
                log.warning("fill_empty line %d failed: %s", u.id, exc)
                continue
            if target == "th" and u.target:
                u.target = spoken(u.target)
            if not u.target.strip() or u.target == before:
                continue
        if u.target.strip():
            filled += 1
    log.info("filled empty targets: %d (restored+AI), still empty: %s",
             filled, [u.id for u in utts if not (u.target or "").strip() and (u.source or "").strip()])
    return filled


def judge_dub_quality(lines: list[dict], check_cancel: Optional[Callable[[], None]] = None) -> dict[int, str]:
    """ตัดสินคุณภาพเสียงพากย์ที่ยังไม่ตรงบท: id → retry|shorten|accept
    lines: [{id, target, heard, score, seconds}]"""
    if not settings.ai_dub_judge or not settings.typhoon_api_key or settings.mock_pipeline or not lines:
        return {int(x["id"]): "retry" for x in lines}
    out: dict[int, str] = {}
    for batch in _chunks(lines, 16):
        if check_cancel:
            check_cancel()
        payload = {"lines": [{"id": x["id"], "target": x["target"], "heard": x.get("heard") or "",
                              "score": round(float(x.get("score") or 0), 3),
                              "seconds": round(float(x.get("seconds") or 0), 1)} for x in batch]}
        try:
            result = _parse_json(_chat(DUB_JUDGE_PROMPT, json.dumps(payload, ensure_ascii=False),
                                       temperature=0.1, max_tokens=min(2048, 80 + 40 * len(batch))))
            for row in result.get("lines", []):
                try:
                    uid, action = int(row["id"]), str(row.get("action") or "").strip().lower()
                except (KeyError, TypeError, ValueError):
                    continue
                if action in ("retry", "shorten", "accept"):
                    out[uid] = action
        except Exception as exc:  # noqa: BLE001
            log.warning("judge_dub_quality failed: %s", exc)
        for x in batch:
            out.setdefault(int(x["id"]), "retry")
    return out


def _around(batch: list[Utterance], order: Optional[list[Utterance]]) -> dict[int, dict]:
    """id → บทก่อนหน้าและถัดไปหนึ่งบรรทัด ใช้ตอนย่อหรือขยาย (แต่ละชุดรวมบรรทัดที่อยู่ห่างกัน โมเดลจึงไม่เห็นว่าบทต่อกันยังไง)"""
    if not (settings.fit_neighbors and order):
        return {}
    at = {u.id: i for i, u in enumerate(order)}
    brief = lambda u: {"speaker": u.speaker, "text": u.target}  # noqa: E731
    out = {}
    for u in batch:
        i = at.get(u.id)
        if i is None:
            continue
        out[u.id] = {**({"before": brief(order[i - 1])} if i > 0 and order[i - 1].target else {}),
                     **({"after": brief(order[i + 1])} if i + 1 < len(order) and order[i + 1].target else {})}
    return out


def fit_lengths(utts: list[Utterance], target: str = "th", max_speedup: float = 1.35,
                only: Optional[set[int]] = None) -> None:
    """ปรับความยาวบทให้พอดีเวลาที่ตัวละครพูด
    ย่อบทที่คาดว่ายาวเกินเวลาที่มี ให้พูดได้ด้วยความเร็วปกติ (สองรอบ รอบสองเฉพาะบรรทัดที่ยังยาวเกิน)
    แล้วขยายบทที่สั้นกว่าเวลาพูดจริงมาก (ไม่ยืดเสียง เสียงยืดฟังยานไม่เป็นธรรมชาติ)
    only: ปรับเฉพาะบรรทัดเหล่านี้ (บทที่เพิ่งแปลใหม่ในขั้นตรวจ)"""
    if not settings.typhoon_api_key:
        return
    tolerance = min(max_speedup, settings.fit_tolerance)
    budget = budgets(utts)
    order = sorted(utts, key=lambda u: u.start)
    for _ in range(2):
        too_long = [u for u in utts if (only is None or u.id in only) and u.duration > 0 and u.target
                    and estimate_seconds(u.target, target) > budget[u.id] * tolerance]
        if not too_long:
            break
        log.info("shorten %d lines: %s", len(too_long), [u.id for u in too_long])
        for batch in _chunks(too_long, settings.translate_batch_size):
            shorten(batch, target, target_ratio=tolerance, budgets=budget, order=order)
    # ท่อนสั้น ๆ (ไม่ถึง 1 วินาที) มักเป็นคำเดียว ขยายแล้วไม่เป็นธรรมชาติ
    too_short = [u for u in utts if (only is None or u.id in only)
                 and settings.fit_min_ratio > 0 and u.duration >= 1.0 and u.target.strip()
                 and estimate_seconds(u.target, target) < u.duration * settings.fit_min_ratio]
    if too_short:
        log.info("lengthen %d lines: %s", len(too_short), [u.id for u in too_short])
        for batch in _chunks(too_short, settings.translate_batch_size):
            lengthen(batch, target, tolerance, order)
    if target == "th":  # บทที่ย่อหรือขยายแล้วอาจมีตัวย่อกลับมา
        for u in utts:
            u.target = spoken(u.target)


def lengthen(batch: list[Utterance], target: str = "th", tolerance: float = 1.1,
             order: Optional[list[Utterance]] = None) -> None:
    """ขยายบทให้ยาวราว 80–100% ของเวลาที่ตัวละครพูด โดยความหมายตรงต้นฉบับ
    ใช้เฉพาะคำตอบที่ยาวขึ้นจริงและไม่เกินเวลาที่มี ขยายไม่ได้ก็ใช้บทเดิม"""
    lo_key, hi_key = ("min_words", "max_words") if target == "en" else ("min_chars", "max_chars")
    around = _around(batch, order)
    payload = [{"id": u.id, "seconds": round(u.duration, 1), lo_key: max_length(u.duration * 0.8, target),
                hi_key: max_length(u.duration, target), "source": u.source, "text": u.target,
                **around.get(u.id, {})} for u in batch]
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
            budgets: Optional[dict[int, float]] = None, order: Optional[list[Utterance]] = None) -> None:
    limit_key = "max_words" if target == "en" else "max_chars"
    around = _around(batch, order)
    payload = []
    for u in batch:
        sec = (budgets or {}).get(u.id, u.duration) * target_ratio
        payload.append({"id": u.id, "seconds": round(sec, 1), limit_key: max_length(sec, target), "text": u.target,
                        **around.get(u.id, {})})
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


# ---------------------------------------------------------------- ตรวจหลังแปล
def _runs(indices: list[int]) -> list[list[int]]:
    """ตำแหน่งที่เรียงแล้ว → ช่วงที่ติดกัน"""
    out: list[list[int]] = []
    for i in indices:
        if out and out[-1][-1] == i - 1:
            out[-1].append(i)
        else:
            out.append([i])
    return out


def _notes(items, allowed: set[int]) -> dict[int, str]:
    out: dict[int, str] = {}
    for x in items or []:
        if isinstance(x, dict) and str(x.get("id", "")).isdigit() and int(x["id"]) in allowed:
            out.setdefault(int(x["id"]), str(x.get("note") or "").strip()[:200])
    return out


def _continuity_breaks(order: list[Utterance], ids: Optional[set[int]] = None,
                       check_cancel: Optional[Callable[[], None]] = None) -> dict[int, str]:
    """id → เหตุผล ของบรรทัดที่ความหมายไม่ต่อกับบทข้างเคียง ids: ตรวจเฉพาะบรรทัดเหล่านี้และบรรทัดที่ติดกัน
    เรียกไม่สำเร็จถือว่าไม่พบ ขั้นตรวจไม่ควรทำให้งานล้ม"""
    picked = list(range(len(order))) if ids is None else sorted(
        {k for i, u in enumerate(order) if u.id in ids for k in range(max(0, i - 1), min(len(order), i + 2))})
    out: dict[int, str] = {}
    for run in _runs(picked):
        for chunk in _chunks(run, settings.translate_batch_size):
            if check_cancel:
                check_cancel()
            payload = {"previous_lines": [{"speaker": u.speaker, "source": u.source, "text": u.target}
                                          for u in order[max(0, chunk[0] - 2):chunk[0]]],
                       "lines": [{"id": order[i].id, "speaker": order[i].speaker, "source": order[i].source,
                                  "text": order[i].target} for i in chunk]}
            try:
                result = _parse_json(_chat(CONTINUITY_PROMPT, json.dumps(payload, ensure_ascii=False), temperature=0.1,
                                           max_tokens=min(4096, 200 + 60 * len(chunk))))
                out.update(_notes(result.get("breaks"), {order[i].id for i in chunk}))
            except Exception as exc:  # noqa: BLE001
                log.warning("continuity check failed: %s", exc)
    return out


def _keep_better_target(old: str, new: str, target: str) -> str:
    """ถ้ารอบแปลใหม่ว่าง / มีอักษรต้นฉบับ / หดสั้นผิดปกติ → คงบทเดิม"""
    old, new = (old or "").strip(), (new or "").strip()
    if not new or FOREIGN_SCRIPT.search(new):
        return old
    if target == "th":
        new = spoken(new)
    if old and len(new) < max(2, int(len(old) * 0.4)):
        return old
    return new


def _retranslate(flagged: dict[int, str], lang: str, target: str, title: str, hints: dict) -> set[int]:
    """แปลใหม่ทั้งประโยคของบรรทัดที่ไม่ต่อกัน พร้อมบอกเหตุผล คืน id ทุกบรรทัดที่ส่งไปแปล
    ส่งทีละช่วงที่ติดกัน ประโยคข้างเคียงของแต่ละชุดจึงถูกต้อง แปลไม่ผ่านหรือแย่กว่าเดิมก็คงบทเดิม"""
    order, at = hints["sentences"], hints["sentence_at"]
    picked = sorted({at[i] for i in flagged})
    issues = {order[k][0].id: "; ".join(flagged[u.id] for u in order[k] if u.id in flagged) for k in picked}
    tried: set[int] = set()
    for run in _runs(picked):
        for batch in _group_batches([order[k] for k in run], settings.translate_batch_size):
            context = [u for g in order[:at[batch[0][0].id]] for u in g][-6:]
            backup = {u.id: u.target for g in batch for u in g}
            _translate_groups(batch, lang, target, context, title, {**hints, "issues": issues})
            for g in batch:
                for u in g:
                    tried.add(u.id)
                    kept = _keep_better_target(backup.get(u.id, ""), u.target, target)
                    if kept != (u.target or "").strip() and kept == (backup.get(u.id) or "").strip():
                        log.info("retranslate kept old line %d (new was empty/worse)", u.id)
                    u.target = kept
    return tried


def _glossary_misses(hints: dict) -> dict[int, str]:
    """ต้นฉบับมีคำใน glossary แต่คำแปลทั้งประโยคไม่มีคำที่กำหนด (เทียบตรง ๆ ไม่ต้องถามโมเดล)"""
    out: dict[int, str] = {}
    for line in _glossary(hints):
        src, _, dst = line.partition("=")
        src, dst = src.strip().lower(), dst.strip().lower()
        if len(src) < 2 or not dst:
            continue
        for g in hints["sentences"]:
            if dst in " ".join(u.target for u in g).lower():
                continue
            for u in g:
                if src in u.source.lower():
                    out.setdefault(u.id, f"คำแปลไม่ตรง glossary: {line}")
    return out


def _term_issues(order: list[Utterance], hints: dict, check_cancel: Optional[Callable[[], None]] = None) -> dict[int, str]:
    out = _glossary_misses(hints)
    for chunk in _chunks(order, TERMS_BATCH_SIZE):
        if check_cancel:
            check_cancel()
        payload = {**({"glossary": _glossary(hints)} if _glossary(hints) else {}),
                   **({"names": hints["names"]} if hints.get("names") else {}),
                   "lines": [{"id": u.id, "speaker": u.speaker, "source": u.source, "text": u.target} for u in chunk]}
        try:
            result = _parse_json(_chat(TERMS_PROMPT, json.dumps(payload, ensure_ascii=False), temperature=0.1,
                                       max_tokens=min(4096, 200 + 40 * len(chunk))))
            for uid, note in _notes(result.get("issues"), {u.id for u in chunk}).items():
                out.setdefault(uid, note)
        except Exception as exc:  # noqa: BLE001
            log.warning("term check failed: %s", exc)
    return out


def review_translation(utts: list[Utterance], lang: str, target: str = "th", max_speedup: float = 1.35,
                       title: str = "", hints: Optional[dict] = None,
                       check_cancel: Optional[Callable[[], None]] = None) -> None:
    """ตรวจบทหลังแปล บรรทัดที่ควรให้คนดูติดป้ายไว้ใน check_note
    - continuous: หาบรรทัดที่ความหมายไม่ต่อกัน แปลใหม่ไม่เกิน REVIEW_ROUNDS รอบ ยังไม่ผ่านจึงติดป้าย
    - อื่น ๆ (teaser หรือไม่รู้ประเภท): ตรวจชื่อและศัพท์อย่างเดียว ติดป้ายโดยไม่แก้บท เพราะฉากไม่ต้องต่อกัน"""
    if same_lang(lang, target):
        ensure_same_lang_targets(utts, lang, target)
        return
    hints = _with_order(utts, hints)
    order = [u for g in hints["sentences"] for u in g]
    if hints.get("content_type") != "continuous":
        issues = _term_issues(order, hints, check_cancel)
        log.info("term check: %d lines to review", len(issues))
    else:
        issues = _continuity_breaks(order, check_cancel=check_cancel)
        for _ in range(REVIEW_ROUNDS):
            if not issues:
                break
            log.info("continuity: retranslate %s", sorted(issues))
            if check_cancel:
                check_cancel()
            try:
                tried = _retranslate(issues, lang, target, title, hints)
            except RuntimeError as exc:  # โควตาหมดหรือเรียกไม่ได้: คงบทเดิมแล้วติดป้าย
                log.warning("retranslate failed: %s", exc)
                break
            fit_lengths(utts, target, max_speedup, only=tried)
            issues = _continuity_breaks(order, tried, check_cancel)
        issues = {uid: f"ความหมายอาจไม่ต่อกับบทข้างเคียง: {note}" for uid, note in issues.items()}
    for u in order:
        u.check_note = issues.get(u.id, "")


def propose_turns(utts: list[Utterance], batch_size: int = 25,
                  only_ids: Optional[set[int]] = None) -> dict[int, list[str]]:
    """id ประโยค → ข้อความที่ตัดตามคนพูด (เฉพาะประโยคที่ควรตัด) จากความหมายของบท
    ระบบแยกผู้พูดฟังแค่เสียง สองคนเสียงคล้ายกันพูดโต้ตอบเร็ว ๆ จะได้ท่อนเดียว แต่บทบอกได้ชัด (ถาม/ตอบ คำรับ)
    ใช้เฉพาะคำตอบที่ต่อกันแล้วตรงกับบทเดิมทุกตัวอักษร (ไม่นับช่องว่าง) เวลาของแต่ละชิ้นหาจากเวลาของคำ
    only_ids: ถ้ามี ตรวจเฉพาะ id เหล่านี้ (ใช้หลัง gate เจอท่อนบวม)"""
    order = sorted(utts, key=lambda u: u.start)
    if only_ids is not None:
        order = [u for u in order if u.id in only_ids]
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
