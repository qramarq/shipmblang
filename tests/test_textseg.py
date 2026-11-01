"""Unicode segmentation, streaming chunks, and the CLI/LSP text that uses them."""

import contextlib
import io
import os
import struct
import sys
import types
import unittest
from unittest.mock import Mock, patch

from shipmblang._compiler import textseg as compiler_textseg
from shipmblang.libraries.textseg import (
    HEADER_SIZE,
    crc16_ccitt,
    chunk_text,
    frame_message,
    graphemes,
    parse_frame,
    sentences,
    slice_text,
    unframe_message,
    words,
    wrap_text,
)
from shipmblang import run_direct_program
from shipmblang.lsp import diagnostics_from_result
from shipmblang.text_runtime import format_prefixed, present_hover, present_message, write_notice


FAMILY = "\U0001F468\u200D\U0001F469\u200D\U0001F467"
FAMILY_VS = "\U0001F468\uFE0F\u200D\U0001F469\uFE0F\u200D\U0001F467\uFE0F"
WAVE = "\U0001F44B\U0001F3FD"


def _join(parts):
    return "".join(parts)


def _frame_body(frames):
    parsed = [parse_frame(frame) for frame in frames]
    parts = [parsed[0]["payload"][2:]]
    parts.extend(item["payload"] for item in parsed[1:])
    return b"".join(parts)


class GraphemeTests(unittest.TestCase):
    def test_combining_mark_skin_tone_zwj_and_flag(self):
        self.assertEqual(graphemes("e\u0301"), ["e\u0301"])
        self.assertEqual(graphemes("café"), ["c", "a", "f", "é"])
        self.assertEqual(graphemes(WAVE), [WAVE])
        self.assertEqual(graphemes(FAMILY), [FAMILY])
        self.assertEqual(graphemes(FAMILY_VS), [FAMILY_VS])
        self.assertEqual(graphemes("🇺🇸🇫🇷"), ["🇺🇸", "🇫🇷"])
        self.assertEqual(graphemes("\r\n"), ["\r\n"])
        self.assertEqual(graphemes("\u1100\u1161\u11A8"), ["\u1100\u1161\u11A8"])
        self.assertEqual(graphemes("\u0915\u094d\u0937"), ["\u0915\u094d\u0937"])

    def test_arabic_harakat_stay_on_their_letter(self):
        text = "مَرْحَبًا"
        self.assertEqual(len(graphemes(text)), 5)
        self.assertEqual(_join(graphemes(text)), text)

    def test_utf8_slice_never_splits_a_byte_or_a_cluster(self):
        acute = "éx"
        self.assertEqual(slice_text(acute, 1, 3), "x")
        self.assertEqual(slice_text(acute, 0, 1), "")
        self.assertEqual(slice_text(acute, 0, 2), "é")
        cluster = "e\u0301X"
        self.assertEqual(slice_text(cluster, 0, 2), "")
        self.assertEqual(slice_text(cluster, 1, 4), "X")
        self.assertEqual(slice_text(cluster, 0, 2, unit="chars"), "e\u0301")
        self.assertEqual(slice_text(FAMILY + "Z", 1, 99), "Z")
        for text in (acute, cluster, FAMILY, "你好"):
            raw = text.encode("utf-8")
            for start in range(len(raw) + 1):
                for end in range(start, len(raw) + 1):
                    piece = slice_text(text, start, end)
                    self.assertTrue(text.find(piece) >= 0 or piece == "")


class WordTests(unittest.TestCase):
    def test_words_follow_script(self):
        self.assertEqual(words("Don't stop."), ["Don't", "stop"])
        self.assertEqual(words("Value 3.14 today"), ["Value", "3.14", "today"])
        self.assertEqual(words("カタカナ"), ["カタカナ"])
        self.assertEqual(words("ひらがな"), list("ひらがな"))
        self.assertEqual(words("你好世界"), list("你好世界"))
        self.assertEqual(words("안녕 하세요"), ["안녕", "하세요"])
        self.assertEqual(words("มากิน", lang="th"), ["มา", "กิน"])
        self.assertEqual(words("ไปโรงเรียน"), ["ไป", "โรง", "เรียน"])

    def test_twelve_languages_have_word_units(self):
        samples = {
            "en": "The small boat left.",
            "es": "El barco salió.",
            "fr": "Le bateau est parti.",
            "de": "Das Boot legt ab.",
            "pt": "O barco partiu.",
            "it": "La barca parte.",
            "ru": "Лодка ушла.",
            "zh": "小船离开了。",
            "ja": "小舟が出た。",
            "ko": "배가 떠났다.",
            "ar": "غادر القارب.",
            "hi": "नाव चली गई।",
        }
        self.assertEqual(len(samples), 12)
        for lang, text in samples.items():
            with self.subTest(lang=lang):
                tokens = words(text, lang)
                self.assertGreaterEqual(len(tokens), 2)
                self.assertEqual(_join(sentences(text, lang)), text)


class SentenceTests(unittest.TestCase):
    def test_twelve_languages(self):
        samples = {
            "en": ("Dr. Smith left. He stayed.", ["Dr. Smith left. ", "He stayed."]),
            "es": ("Hola. ¿Cómo estás? ¡Muy bien!", ["Hola. ", "¿Cómo estás? ", "¡Muy bien!"]),
            "fr": ("Mme. Curie a gagné. M. Pasteur aussi.", ["Mme. Curie a gagné. ", "M. Pasteur aussi."]),
            "de": (
                "Ich weiß, dass er kommt. Das steht z.B. im Bericht, weil er bleibt.",
                ["Ich weiß, dass er kommt. ", "Das steht z.B. im Bericht, weil er bleibt."],
            ),
            "pt": ("O Sr. Silva chegou. A Sra. Costa saiu.", ["O Sr. Silva chegou. ", "A Sra. Costa saiu."]),
            "it": ("Il Sig. Rossi arriva. La Sig.ra Bianchi parte.", ["Il Sig. Rossi arriva. ", "La Sig.ra Bianchi parte."]),
            "ru": ("г. Москва большой. См. также приложение.", ["г. Москва большой. ", "См. также приложение."]),
            "zh": ("你好。世界。", ["你好。", "世界。"]),
            "ja": ("こんにちは。元気ですか？", ["こんにちは。", "元気ですか？"]),
            "ko": ("안녕하세요. 반갑습니다.", ["안녕하세요. ", "반갑습니다."]),
            "ar": ("مرحبا. كيف حالك؟ أنا بخير.", ["مرحبا. ", "كيف حالك؟ ", "أنا بخير."]),
            "hi": ("नमस्ते। आप कैसे हैं? मैं ठीक हूँ।", ["नमस्ते। ", "आप कैसे हैं? ", "मैं ठीक हूँ।"]),
        }
        self.assertEqual(len(samples), 12)
        for lang, (text, expected) in samples.items():
            with self.subTest(lang=lang):
                self.assertEqual(sentences(text, lang), expected)
                self.assertEqual(_join(sentences(text, lang)), text)

    def test_abbreviations_quotes_brackets_and_ellipsis(self):
        self.assertEqual(sentences("See e.g. this one. Next.", lang="en"), ["See e.g. this one. ", "Next."])
        self.assertEqual(sentences("Er kommt bzw. Er geht nach Hause.", lang="de"), ["Er kommt bzw. Er geht nach Hause."])
        self.assertEqual(sentences('He said "Go." Then he left.'), ['He said "Go." ', "Then he left."])
        self.assertEqual(sentences('He said "Go". Then he left.'), ['He said "Go". ', "Then he left."])
        self.assertEqual(sentences("Done.) Next starts."), ["Done.) ", "Next starts."])
        self.assertEqual(sentences("Er sagte „Halt.“ Dann ging er.", lang="de"), ["Er sagte „Halt.“ ", "Dann ging er."])
        self.assertEqual(sentences("«Готово.» Дальше.", lang="ru"), ["«Готово.» ", "Дальше."])
        self.assertEqual(
            sentences("Wait... really? Yes… Next sentence."),
            ["Wait... really? ", "Yes… ", "Next sentence."],
        )
        self.assertEqual(sentences("Hello. world stays", lang="en"), ["Hello. world stays"])
        self.assertEqual(sentences("Hello. World moves", lang="en"), ["Hello. ", "World moves"])

    def test_no_space_scripts_and_enders(self):
        self.assertEqual(sentences("你好世界没有空格。下一句。", lang="zh"), ["你好世界没有空格。", "下一句。"])
        self.assertEqual(sentences("ไปโรงเรียนฯ กลับบ้าน", lang="th"), ["ไปโรงเรียนฯ ", "กลับบ้าน"])
        self.assertEqual(sentences("หนังสือฯลฯ มีอยู่", lang="th"), ["หนังสือฯลฯ มีอยู่"])
        self.assertEqual(len(sentences("مرحبا؟طيب.", lang="ar")), 2)
        self.assertEqual(sentences("क्या?हाँ।", lang="hi")[0], "क्या?")

    def test_emoji_sentence_keeps_the_cluster(self):
        text = f"Done {FAMILY}. Next."
        parts = sentences(text, lang="en")
        self.assertEqual(parts, [f"Done {FAMILY}. ", "Next."])
        self.assertIn(FAMILY, parts[0])


class ChunkTests(unittest.TestCase):
    def test_byte_cap_on_multibyte_text(self):
        text = "你好世界"
        parts = chunk_text(text, max_bytes=7, lang="zh")
        self.assertEqual(parts, ["你好", "世界"])
        self.assertTrue(all(len(part.encode("utf-8")) <= 7 for part in parts))
        self.assertEqual(_join(parts), text)

    def test_overlong_grapheme_stays_whole(self):
        text = FAMILY + " next"
        parts = chunk_text(text, max_bytes=4, lang="en")
        self.assertIn(FAMILY, parts)
        self.assertEqual(_join(parts), text)
        for part in parts:
            self.assertEqual(part.encode("utf-8").decode("utf-8"), part)

    def test_soft_break_and_max_words(self):
        text = "Hello, this phrase keeps going well past forty bytes."
        parts = chunk_text(text, max_bytes=40, lang="en")
        self.assertEqual(_join(parts), text)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(part.encode("utf-8")) <= 40 for part in parts))
        self.assertTrue(parts[0].endswith((" ", ",")))
        words_only = chunk_text("one two three four", max_words=2, lang="en")
        self.assertEqual(_join(words_only), "one two three four")
        self.assertTrue(all(len(part.split()) <= 2 for part in words_only))

    def test_german_trailing_verb_is_not_left_alone(self):
        text = "Er sagt, dass er heute sehr spät kommt."
        parts = chunk_text(text, max_bytes=200, max_words=7, lang="de")
        self.assertEqual(_join(parts), text)
        self.assertTrue(all(part.strip() != "kommt." for part in parts))
        self.assertTrue(any("kommt" in part and "spät" in part for part in parts))

    def test_hard_break_is_on_a_character_boundary(self):
        text = "supercalifragilistic"
        parts = chunk_text(text, max_bytes=8, lang="en")
        self.assertEqual(parts, ["supercal", "ifragili", "stic"])
        acute = "éééé"
        pieces = chunk_text(acute, max_bytes=5, lang="fr")
        self.assertEqual(_join(pieces), acute)
        self.assertTrue(all(len(piece.encode("utf-8")) <= 5 for piece in pieces))

    def test_join_identity_for_a_mixed_paragraph(self):
        text = f'Dr. Müller sagte „Halt.“ 你好。Wait... really? {FAMILY} Done.) Next.\n'
        parts = chunk_text(text, max_bytes=24, max_words=6)
        self.assertEqual(_join(parts), text)


class FrameTests(unittest.TestCase):
    def test_ccitt_and_round_trip(self):
        self.assertEqual(crc16_ccitt(b"123456789"), 0x29B1)
        self.assertEqual(HEADER_SIZE, 8)
        payload = "你" * 80 + " " + FAMILY
        frames = frame_message(7, payload)
        self.assertGreater(len(frames), 1)
        self.assertTrue(all(len(frame) <= 150 for frame in frames))
        parsed = [parse_frame(frame) for frame in frames]
        self.assertEqual([item["chunk_idx"] for item in parsed], list(range(len(frames))))
        self.assertTrue(all(
            item["sentence_idx"] == 0 and item["total"] == len(frames) and item["msg_id"] == 7
            for item in parsed
        ))
        self.assertTrue(all(item["flags"] == 0x01 for item in parsed))
        self.assertEqual(parsed[0]["payload"][:2], b"\x00\x00")
        self.assertEqual(unframe_message(frames).decode("utf-8"), payload)
        broken = bytearray(frames[0])
        broken[-1] ^= 0xFF
        with self.assertRaises(ValueError):
            parse_frame(bytes(broken))

    def test_header_is_eight_bytes_and_little_endian(self):
        frames = frame_message(7, "Hi")
        self.assertEqual(len(frames), 1)
        frame = frames[0]
        self.assertEqual(len(frame) - len(parse_frame(frame)["payload"]), 8)
        self.assertEqual(frame[0:2], b"\x07\x00")
        self.assertEqual(list(frame[2:6]), [0, 0, 1, 0x01])
        self.assertEqual(int.from_bytes(frame[6:8], "little"), crc16_ccitt(frame[8:]))
        msg_id, sentence_idx, chunk_idx, total, flags, crc = struct.unpack("<HBBBBH", frame[:8])
        self.assertEqual((msg_id, sentence_idx, chunk_idx, total, flags), (7, 0, 0, 1, 0x01))
        self.assertEqual(crc, crc16_ccitt(frame[8:]))
        self.assertEqual(frame[8:10], b"\x00\x00")
        self.assertEqual(frame[10:], b"Hi")
        self.assertEqual(unframe_message(frames), b"Hi")

    def test_high_message_id_bytes_lead_the_first_payload(self):
        frames = frame_message(0x12345678, "AB")
        self.assertEqual(frames[0][:2], struct.pack("<H", 0x5678))
        self.assertEqual(frames[0][8:10], struct.pack("<H", 0x1234))
        self.assertEqual(parse_frame(frames[0])["msg_id"], 0x5678)
        self.assertEqual(parse_frame(frames[0])["payload"][2:], b"AB")
        self.assertEqual(unframe_message(frames), b"AB")
        preserved = struct.unpack_from("<H", frames[0], 8)[0]
        self.assertEqual((preserved << 16) | frames[0][0] | (frames[0][1] << 8), 0x12345678)
        nulled = frame_message(4, b"\x00\x00Hi")
        self.assertEqual(unframe_message(nulled), b"\x00\x00Hi")

    def test_encoder_never_sets_control_and_decoder_rejects_it(self):
        frames = frame_message(9, "One. Two sentences.")
        self.assertTrue(all((frame[5] & 0x04) == 0 for frame in frames))
        self.assertTrue(all(frame[5] in (0x00, 0x01) for frame in frames))
        self.assertEqual(parse_frame(frames[0])["flags"] & 0x01, 0)
        self.assertEqual(parse_frame(frames[-1])["flags"] & 0x01, 0x01)
        control = bytearray(frames[0])
        control[5] |= 0x04
        with self.assertRaises(ValueError) as caught:
            parse_frame(bytes(control))
        self.assertIn("control", str(caught.exception))
        with self.assertRaises(ValueError):
            unframe_message([bytes(control), *frames[1:]])

    def test_cuts_stay_on_utf8_and_grapheme_boundaries(self):
        text = "é" * 5 + FAMILY
        frames = frame_message(1, text, max_frame=HEADER_SIZE + 2 + 3)
        self.assertGreater(len(frames), 1)
        body = _frame_body(frames)
        self.assertEqual(body, text.encode("utf-8"))
        for frame in frames:
            piece = parse_frame(frame)["payload"]
            if frame is frames[0]:
                piece = piece[2:]
            piece.decode("utf-8")
        self.assertEqual(unframe_message(frames).decode("utf-8"), text)
        whole = frame_message(3, FAMILY, max_frame=HEADER_SIZE + 2 + 4)
        self.assertEqual(len(whole), 1)
        self.assertGreater(len(whole[0]), HEADER_SIZE + 2 + 4)
        self.assertEqual(unframe_message(whole).decode("utf-8"), FAMILY)

    def test_sentences_have_their_own_chunk_totals(self):
        frames = frame_message(5, "Hi. Yo.")
        parsed = [parse_frame(frame) for frame in frames]
        self.assertEqual([item["sentence_idx"] for item in parsed], [0, 1])
        sentences_seen = {item["sentence_idx"] for item in parsed}
        self.assertEqual(sentences_seen, set(range(max(sentences_seen) + 1)))
        for item in parsed:
            siblings = [other for other in parsed if other["sentence_idx"] == item["sentence_idx"]]
            self.assertEqual(item["total"], len(siblings))
            self.assertEqual([other["chunk_idx"] for other in siblings], list(range(len(siblings))))
        self.assertEqual(unframe_message(frames).decode("utf-8"), "Hi. Yo.")
        longer = ("你" * 80) + "。End."
        longer_frames = frame_message(7, longer)
        longer_parsed = [parse_frame(frame) for frame in longer_frames]
        self.assertGreater(longer_parsed[0]["total"], 1)
        self.assertGreater(longer_parsed[-1]["sentence_idx"], 0)
        self.assertEqual(longer_parsed[-1]["flags"] & 0x01, 0x01)
        self.assertEqual(longer_parsed[0]["flags"] & 0x01, 0)
        self.assertEqual(unframe_message(longer_frames).decode("utf-8"), longer)

    def test_empty_and_binary_payloads(self):
        empty = frame_message(1, "")
        self.assertEqual(len(empty), 1)
        self.assertEqual(len(empty[0]), HEADER_SIZE + 2)
        self.assertEqual(unframe_message(empty), b"")
        blob = bytes(range(256)) * 2
        frames = frame_message(2, blob)
        self.assertTrue(all(len(frame) <= 150 for frame in frames))
        budget = 150 - HEADER_SIZE
        first = budget - 2
        self.assertEqual(frames[0][8:], b"\x00\x00" + blob[:first])
        self.assertEqual(frames[1][8:], blob[first:first + budget])
        self.assertEqual(unframe_message(frames), blob)

    def test_uint8_sentence_and_chunk_limits(self):
        with self.assertRaises(ValueError):
            frame_message(1, "a" * (2 + 255 * 4), max_frame=HEADER_SIZE + 4)
        with self.assertRaises(ValueError):
            frame_message(1, "A. " * 257)

    def test_audio_flag_is_not_control(self):
        frame = bytearray(frame_message(1, "Hi")[0])
        frame[5] |= 0x02
        parsed = parse_frame(bytes(frame))
        self.assertEqual(parsed["flags"] & 0x02, 0x02)
        self.assertEqual(unframe_message([bytes(frame)]), b"Hi")


class ProductTests(unittest.TestCase):
    def test_short_notice_is_unchanged_and_long_notice_wraps(self):
        short = format_prefixed("shipmblang: SMBM001: ", "Memory unavailable")
        self.assertEqual(short, "shipmblang: SMBM001: Memory unavailable")
        from shipmblang.pipelines import VISION_LIBRARY_REQUIRED
        from shipmblang.setup_tools import SETUP_HINT

        self.assertNotIn("\n", format_prefixed("shipmblang: ", VISION_LIBRARY_REQUIRED))
        self.assertNotIn("\n", format_prefixed("shipmblang: ", SETUP_HINT))
        long = "The compiler rejected this sentence, and the explanation continues " * 3
        wrapped = format_prefixed("shipmblang: ", long.strip())
        self.assertIn("\n", wrapped)
        self.assertIn("The compiler rejected this sentence,", wrapped)
        self.assertEqual(wrapped.replace("\n", "").replace("  ", ""), "shipmblang: " + long.strip().replace("  ", ""))

    def test_notice_streams_without_dropping_text(self):
        stream = io.StringIO()
        message = "Memory unavailable"
        write_notice(stream, message, prefix="shipmblang: SMBM001: ")
        self.assertEqual(stream.getvalue(), "shipmblang: SMBM001: Memory unavailable\n")

    def test_lsp_wraps_a_long_diagnostic_and_keeps_hover_code(self):
        short = diagnostics_from_result("Show 1.", {"diagnostics": [{
            "message": "Memory unavailable", "span": {"start": 0, "end": 4}, "level": "error", "code": "X",
        }]})
        self.assertEqual(short[0]["message"], "Memory unavailable")
        long = "The compiler rejected this sentence, and the explanation continues so the editor can show the rest. It then adds a second sentence that is also long enough to wrap."
        item = diagnostics_from_result("Show 1.", {"diagnostics": [{
            "message": long, "span": {"start": 0, "end": 4}, "level": "error", "code": "X",
        }]})[0]
        self.assertIn("\n", item["message"])
        self.assertIn("The compiler rejected this sentence,", item["message"])
        self.assertIn("second sentence", item["message"])
        hover = "```\nShow 1.\n```\n\nThis line compiles to:\n\n- `const 1`"
        self.assertEqual(present_hover(hover), hover)
        prose = present_message(long)
        self.assertIn("\n", prose)
        self.assertLessEqual(max(len(line) for line in prose.split("\n")), 96)

    def test_cli_warning_still_contains_the_message(self):
        from shipmblang import pipelines

        artifact = {"producer": "shipmbcompiler", "version": "0.2", "bytecode": []}
        result = {"status": "compiled", "pipeline": "direct", "diagnostics": [
            {"level": "warning", "code": "SMBM001", "message": "Memory unavailable"},
        ], "target_code": artifact, "core_source": None}
        compiler = types.ModuleType("shipmblang._compiler")
        compiler.compile_direct_program = Mock(return_value=result)
        stderr = io.StringIO()
        with patch.dict(sys.modules, {"shipmblang._compiler": compiler}), patch.dict(os.environ, {"SHIPMB_MEMORY": "off"}):
            with patch.object(sys, "argv", ["compile", "--pipeline", "direct", "Use ShipMB."]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                pipelines.main()
        self.assertIn("Memory unavailable", stderr.getvalue())
        self.assertIn("SMBM001", stderr.getvalue())

    def test_wrap_does_not_split_a_wide_character(self):
        text = "你好" * 40
        wrapped = wrap_text(text, width=16, lang="zh")
        for line in wrapped.split("\n"):
            self.assertLessEqual(sum(2 for _ in line), 16)
            self.assertEqual(line.encode("utf-8").decode("utf-8"), line)
        self.assertEqual(wrapped.replace("\n", ""), text)


class CompilerTextsegTests(unittest.TestCase):
    def test_library_reexports_the_bundled_compiler(self):
        self.assertIs(graphemes, compiler_textseg.graphemes)
        self.assertIs(words, compiler_textseg.words)
        self.assertIs(sentences, compiler_textseg.sentences)
        self.assertIs(chunk_text, compiler_textseg.chunk_text)
        self.assertIs(frame_message, compiler_textseg.frame_message)
        self.assertIs(wrap_text, compiler_textseg.wrap_text)

    def test_programs_use_the_bundled_segmenter(self):
        grapheme = run_direct_program('Show the graphemes of "cafe".\n', memory=False, model_provider=None)
        self.assertEqual(grapheme["status"], "compiled", grapheme)
        self.assertEqual(grapheme["runtime"]["stdout"], "[c, a, f, e]\n")
        sentence = run_direct_program(
            'Show the sentences of "Dr. Smith left. He stayed." in "english".\n',
            memory=False,
            model_provider=None,
        )
        self.assertEqual(sentence["status"], "compiled", sentence)
        self.assertEqual(sentence["runtime"]["stdout"], "[Dr. Smith left. , He stayed.]\n")
        framed = run_direct_program('Show the frames of "Hi" for message 7.\n', memory=False, model_provider=None)
        self.assertEqual(framed["status"], "compiled", framed)
        text = framed["runtime"]["stdout"].strip()
        self.assertTrue(text.startswith("[") and text.endswith("]"), text)
        hex_frames = [item.strip() for item in text[1:-1].split(",")]
        raw = [bytes.fromhex(item) for item in hex_frames]
        self.assertTrue(all(len(frame) >= 8 for frame in raw))
        self.assertEqual(struct.unpack_from("<HBBBB", raw[0])[:4], (7, 0, 0, 1))
        self.assertEqual(raw[0][5] & 0x04, 0)
        self.assertEqual(unframe_message(raw), b"Hi")


if __name__ == "__main__":
    unittest.main()
