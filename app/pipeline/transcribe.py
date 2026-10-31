"""ถอดเสียงพร้อมตรวจภาษาอัตโนมัติ (faster-whisper) แล้วจับคู่แต่ละคำกับผู้พูด"""
import unicodedata
from pathlib import Path
from typing import Optional

from ..config import settings
from ..schemas import Utterance
from .common import Turn, Word

_model = None


def _load():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        device, compute = settings.device, settings.whisper_compute_type
        try:
            import torch
            if device.startswith("cuda") and not torch.cuda.is_available():
                device, compute = "cpu", "int8"
        except ImportError:
            device, compute = "cpu", "int8"
        _model = WhisperModel(settings.whisper_model, device=device.split(":")[0], compute_type=compute)
    return _model


def unload() -> None:
    global _model
    _model = None


def transcribe(wav16k: Path, language: Optional[str] = None) -> tuple[list[Word], str]:
    model = _load()
    segments, info = model.transcribe(
        str(wav16k),
        language=language,
        vad_filter=True,
        word_timestamps=True,
        beam_size=5,
        condition_on_previous_text=False,  # กันอาการพูดวนซ้ำ
    )
    words: list[Word] = []
    for i, seg in enumerate(segments):
        if seg.words:
            words += [Word(w.start, w.end, w.word, i) for w in seg.words]
        elif seg.text.strip():
            words.append(Word(seg.start, seg.end, seg.text, i))
    return words, info.language


def clip_text(audio16k, language: Optional[str] = None) -> str:
    """ข้อความทั้งหมดที่พูดในคลิปสั้น ๆ (ไม่ตัดเสียงอุทาน) ใช้เป็นข้อความกำกับเสียงตัวอย่าง"""
    segments, _ = _load().transcribe(audio16k, language=language, vad_filter=False, beam_size=5,
                                     condition_on_previous_text=False)
    return " ".join(" ".join(s.text.strip() for s in segments).split())


# เสียงอุทานที่ไม่ต้องแปล (เทียบหลังยุบตัวอักษรซ้ำ เช่น aaahhh → ah)
INTERJECTIONS = {
    "a", "ah", "aha", "ahah", "aw", "ay", "eh", "ew", "gah", "ha", "hah", "haha", "hey", "hm", "hmm", "ho", "hoho",
    "hooray", "huh", "hu", "mm", "mhm", "o", "oh", "oho", "oops", "ouch", "ow", "oy",
    "phew", "pfft", "shh", "sh", "ugh", "uh", "um", "whoa", "wo", "wow", "woo", "wah", "ya", "yah", "yay", "yeah",
    "yo", "yoohoo", "argh", "ar", "eek", "hiya", "oof", "woohoo", "whoo", "yahoo", "yeehaw", "boo", "agh", "aiya", "ayah",
    "啊", "哈", "嗯", "哦", "噢", "呀", "哎", "唉", "哇", "呃", "嘿", "喔", "呵", "嘛", "吧", "呜", "额", "唔",
    "あ", "ああ", "え", "ええ", "お", "おお", "う", "うわ", "きゃ", "は", "へ", "ほ", "ん", "や",
    "아", "어", "오", "와", "에", "음", "헉", "으",
}


def words_in(audio16k, language: Optional[str] = None) -> str:
    """คำพูดจริงที่ได้ยินในเสียงสั้น ๆ (ตัดเสียงอุทานออก) ถ้าว่างแปลว่าเป็นเสียงร้อง กรี๊ด หัวเราะ หรือหายใจ"""
    import re

    segments, _ = _load().transcribe(audio16k, language=language, vad_filter=False, beam_size=1,
                                     temperature=0.0, condition_on_previous_text=False)
    collapse = lambda t: re.sub(r"(.)\1+", r"\1", t)  # noqa: E731
    known = INTERJECTIONS | {collapse(x) for x in INTERJECTIONS}
    tokens = re.findall(r"[^\W\d_]+", " ".join(s.text for s in segments).lower())
    return " ".join(t for t in tokens if t not in known and collapse(t) not in known)


def _speaker_at(t: float, turns: list[Turn]) -> str:
    active = [x for x in turns if x.start <= t <= x.end]
    if active:  # ถ้าพูดซ้อนกัน เลือกคนที่ช่วงพูดสั้นกว่า (มักเป็นคนที่แทรกเข้ามา)
        return min(active, key=lambda x: x.end - x.start).speaker
    return min(turns, key=lambda x: min(abs(t - x.start), abs(t - x.end))).speaker


SENTENCE_END = tuple(".!?。！？…")


def _snap_changes(words: list[Word], labels: list[str], window: float = 0.5) -> list[str]:
    """เลื่อนจุดเปลี่ยนผู้พูดไปที่ช่องว่างระหว่างคำที่กว้างที่สุดในระยะ window วินาที (จุดจบประโยคได้เปรียบ)

    เวลาของ pyannote คลาดได้ราวหนึ่งพยางค์ ภาษาที่ไม่เว้นวรรคจึงถูกตัดกลางคำ เช่น "なんですか解|決できなければ"
    คนสองคนส่งบทต่อกันมักมีช่องว่างสั้น ๆ ระหว่างคำ จุดนั้นจึงเป็นรอยต่อที่ถูกกว่า
    """
    labels = list(labels)
    for i in range(1, len(words)):
        if labels[i] == labels[i - 1]:
            continue
        t = words[i].start
        lo = i
        while lo > 1 and t - words[lo - 1].start <= window and labels[lo - 2] == labels[i - 1]:
            lo -= 1
        hi = i
        while hi + 1 < len(words) and words[hi + 1].start - t <= window and labels[hi + 1] == labels[i]:
            hi += 1

        def score(k: int) -> float:
            gap = words[k].start - words[k - 1].end
            return gap + (1.0 if words[k - 1].text.strip().endswith(SENTENCE_END) else 0.0)

        best = max(range(lo, hi + 1), key=score)
        if best != i and score(best) > score(i) + 0.05:
            a, b = labels[i - 1], labels[i]
            if best < i:
                labels[best:i] = [b] * (i - best)
            else:
                labels[i:best] = [a] * (best - i)
    return labels


_tokenizers: dict = {}


def _tokenize(text: str, lang: str) -> Optional[list[str]]:
    """ตัดคำภาษาที่ไม่เว้นวรรค (ญี่ปุ่น: Janome, จีน: jieba, ไทย: PyThaiNLP) ไม่มีไลบรารีก็คืน None"""
    try:
        if lang == "th":
            from pythainlp.tokenize import word_tokenize
            return word_tokenize(text, engine="newmm", keep_whitespace=True)
        if lang == "ja":
            if "ja" not in _tokenizers:
                from janome.tokenizer import Tokenizer
                _tokenizers["ja"] = Tokenizer(wakati=True)
            return list(_tokenizers["ja"].tokenize(text))
        if lang in ("zh", "yue"):
            import jieba
            return jieba.lcut(text)
    except ImportError:
        return None
    return None


def _snap_to_words(words: list[Word], labels: list[str], lang: str, max_move: int = 3) -> list[str]:
    """ภาษาที่ไม่เว้นวรรค Whisper ให้คำละตัวอักษร ถ้าจุดเปลี่ยนผู้พูดตกกลางคำ (เช่น "解|決") ให้ย้ายไปขอบคำ
    เวลาของ Whisper ตรงรอยต่อพวกนี้มักคลาด (ใช้เสียงตัดสินไม่ได้) จึงใช้ตัวตัดคำของภาษานั้นแทน"""
    labels = list(labels)
    for i in range(1, len(words)):
        if labels[i] == labels[i - 1]:
            continue
        lo, hi = max(0, i - 8), min(len(words), i + 8)
        texts = [words[k].text.strip() for k in range(lo, hi)]
        starts, pos = [], 0  # ตำแหน่งตัวอักษรที่แต่ละคำเริ่ม
        for t in texts:
            starts.append(pos)
            pos += len(t)
        tokens = _tokenize("".join(texts), lang)
        if not tokens:
            return labels
        bounds, pos = {0}, 0
        for tok in tokens:
            pos += len(tok)
            bounds.add(pos)
        cut = starts[i - lo]
        if cut in bounds:
            continue
        before = max((b for b in bounds if b < cut), default=None)
        after = min((b for b in bounds if b > cut), default=None)
        options = [(abs(starts.index(b) + lo - i), starts.index(b) + lo)
                   for b in (before, after) if b is not None and b in starts]
        if not options:
            continue
        move, k = min(options)  # ย้ายน้อยที่สุด เท่ากันให้ไปขอบหน้า (ยกทั้งคำให้คนถัดไป)
        if move == 0 or move > max_move:
            continue
        if k < i:
            labels[k:i] = [labels[i]] * (i - k)
        else:
            labels[i:k] = [labels[i - 1]] * (k - i)
    return labels


def smooth_speakers(words: list[Word], labels: list[str], lang: str = "", min_sec: float = 1.0) -> list[str]:
    """ยุบช่วงที่ผู้พูดสลับไปแค่ชั่วครู่กลางประโยคเข้ากับช่วงข้าง ๆ

    pyannote มักสลับผู้พูดไปมากลางประโยค (โดยเฉพาะมีเพลงหรือคนพูดเร็ว) ถ้าตัดท่อนตามทุกครั้ง
    คำจะขาดกลางคำ เช่น "カ|ンちゃん" (ภาษาที่ไม่เว้นวรรค Whisper ให้คำละตัวอักษร) แล้วแปลผิดความหมาย
    ชิ้น (คำต่อเนื่องของคนเดียว ไม่ข้ามจุดจบประโยคหรือช่วงเงียบ) ที่สั้นกว่า min_sec และยังไม่จบประโยค
    ถือว่าเป็นของคนข้าง ๆ (ข้างที่ติดกันมากกว่า ถ้าท่อนก่อนจบประโยคแล้วให้ไปกับท่อนหลัง)
    ชิ้นสั้นที่จบประโยคเอง เช่น "Mom!" คงไว้ เพราะมักเป็นอีกคนพูดแทรกจริง
    """
    labels = list(labels)
    ends = lambda k: words[k].text.strip().endswith(SENTENCE_END)  # noqa: E731
    changes = lambda ls: sum(a != b for a, b in zip(ls, ls[1:]))  # noqa: E731
    skip: set = set()  # ชิ้นที่ยุบแล้วไม่ทำให้จุดเปลี่ยนผู้พูดลดลง
    seen = {tuple(labels)}  # กันสลับไปมาไม่จบ (ย้ายจุดเปลี่ยนไปกลับระหว่างสองจุดจบประโยค)
    for _ in range(10 * len(words) + 10):
        runs, i = [], 0
        while i < len(words):
            j = i + 1
            while (j < len(words) and labels[j] == labels[i] and not ends(j - 1)
                   and words[j].start - words[j - 1].end <= 0.5):
                j += 1
            runs.append((i, j))
            i = j
        for k, (i, j) in enumerate(runs):
            if words[j - 1].end - words[i].start >= min_sec or ends(j - 1) or (i, j, labels[i]) in skip:
                continue
            prev_ok = k > 0 and labels[i - 1] != labels[i]
            next_ok = j < len(words) and labels[j] != labels[i]
            if not (prev_ok or next_ok):
                continue  # ข้าง ๆ เป็นคนเดียวกันอยู่แล้ว (แค่ถูกคั่นด้วยจุดจบประโยคหรือช่วงเงียบ)
            if not prev_ok:
                to = j
            elif not next_ok:
                to = i - 1
            elif ends(i - 1):
                to = j  # ท่อนก่อนจบประโยคแล้ว ชิ้นนี้เป็นหัวประโยคถัดไป
            else:
                to = i - 1 if words[i].start - words[i - 1].end < words[j].start - words[j - 1].end else j
            trial = labels[:i] + [labels[to]] * (j - i) + labels[j:]
            # ยอมรับเมื่อจุดเปลี่ยนผู้พูดลดลง หรือเท่าเดิมแต่ย้ายไปอยู่ตรงจุดจบประโยค/ช่วงเงียบ
            edge = i if to == j else j
            clean = 0 < edge < len(words) and (ends(edge - 1) or words[edge].start - words[edge - 1].end > 0.5)
            if (changes(trial) > changes(labels) or (changes(trial) == changes(labels) and not clean)
                    or tuple(trial) in seen):
                skip.add((i, j, labels[i]))
                continue
            labels = trial
            seen.add(tuple(labels))
            break
        else:
            break
    labels = _snap_changes(words, labels)
    if lang in ("ja", "zh", "yue", "th"):
        labels = _snap_to_words(words, labels, lang)
    return _keep_thai_clusters(words, labels) if lang == "th" else labels


THAI_LEADING = tuple("เแโใไ")  # สระหน้า ต้องอยู่กับพยัญชนะตัวถัดไป
THAI_FOLLOWING = set("ะาำๅๆ")  # สระหลังและเครื่องหมายที่ขึ้นต้นพยางค์เองไม่ได้


def _cluster_start(words: list[Word], i: int) -> bool:
    """ตัดก่อนคำที่ i ได้โดยไม่ทำให้พยางค์ไทยแตก (เช่น "ย|ัง", "ข|ึ้น", "แ|ห่")"""
    head, prev = words[i].text.lstrip(), words[i - 1].text.rstrip()
    if not head or not prev:
        return True
    return not (unicodedata.category(head[0]) == "Mn" or head[0] in THAI_FOLLOWING or prev.endswith(THAI_LEADING))


def _keep_thai_clusters(words: list[Word], labels: list[str]) -> list[str]:
    """Whisper ให้เวลาภาษาไทยทีละตัวอักษร ถ้าจุดเปลี่ยนผู้พูดยังตกกลางพยางค์ ยกทั้งพยางค์ให้คนถัดไป
    ตัวตัดคำแก้ได้เกือบหมดแล้ว อันนี้กันกรณีที่ตัดคำไม่ออก (ชื่อเฉพาะ คำที่ถอดเสียงผิด)"""
    labels = list(labels)
    for i in range(1, len(words)):
        if labels[i] == labels[i - 1] or _cluster_start(words, i):
            continue
        k = i
        while k > 1 and not _cluster_start(words, k) and i - k < 4:
            k -= 1
        labels[k:i] = [labels[i]] * (i - k)
    return labels


def assign_speakers(words: list[Word], turns: list[Turn], max_len: Optional[float] = None,
                    lang: str = "") -> list[Utterance]:
    """รวมคำต่อเนื่องของคนเดียวกันเป็นประโยค

    ตัดใหม่เมื่อเปลี่ยนคนพูด เงียบเกิน 1 วินาที ยาวเกิน max_len หรือจบประโยค/ท่อนของ Whisper ตอนที่ยาวพอแล้ว
    ประโยคสั้นได้ใช้เสียงต้นฉบับของตัวเองเป็นเสียงตัวอย่าง จึงได้โทนและอารมณ์ตรงฉาก และ F5-TTS พากย์ได้รวดเดียว
    """
    max_len = max_len or settings.max_line_sec
    soft_len = max(settings.ref_min_sec, max_len / 2)
    utterances: list[Utterance] = []
    group: list[Word] = []
    speaker = ""
    labels = smooth_speakers(words, [_speaker_at((w.start + w.end) / 2, turns) for w in words], lang)

    def flush():
        text = "".join(w.text for w in group).strip()
        if text:
            utterances.append(Utterance(
                id=len(utterances) + 1, speaker=speaker,
                start=round(group[0].start, 3), end=round(group[-1].end, 3), source=text))

    for w, spk in zip(words, labels):
        if group:
            boundary = w.segment != group[-1].segment or group[-1].text.strip().endswith(SENTENCE_END)
            long_enough = group[-1].end - group[0].start >= soft_len
            too_long = w.end - group[0].start > max_len
            split = spk != speaker or w.start - group[-1].end > 1.0 or too_long or (boundary and long_enough)
            if split and lang == "th" and spk == speaker and not _cluster_start([group[-1], w], 1):
                split = False  # ตัดเพราะยาวหรือจบท่อน Whisper แต่ตกกลางพยางค์ไทย → ต่อไปอีกตัว
            if split:
                # หางสั้น ๆ หลังจุดจบประโยค (เช่น "I'm a witch. If") เป็นหัวประโยคถัดไปของคนเดิม → ยกไปด้วย
                carry: list[Word] = []
                if spk == speaker and not group[-1].text.strip().endswith(SENTENCE_END):
                    m = max((k for k, x in enumerate(group[:-1]) if x.text.strip().endswith(SENTENCE_END)), default=None)
                    if m is not None and len(group) - m - 1 <= 3 and group[-1].end - group[m + 1].start <= 1.0:
                        group, carry = group[: m + 1], group[m + 1:]
                flush()
                group = carry
        if not group:
            speaker = spk
        group.append(w)
    if group:
        flush()
    return utterances
