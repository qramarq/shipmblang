from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .limits import MAX_THESAURUS_FILE_BYTES, MAX_WORDNET_FILE_BYTES, read_text_limited


CANONICAL_TRIGGERS: dict[str, set[str]] = {
    "use": {"use", "utilize", "employ", "apply"},
    "library": {"library", "package", "module", "lib", "pkg"},
    "device": {"device", "hardware", "machine"},
    "target": {"target", "destination"},
    "device_target": {"device_target", "device target"},
    "control": {"control", "operate", "command", "drive", "steer"},
    "remote": {"remote", "controller", "remote controller"},
    "search": {"search", "find", "lookup", "look up", "seek"},
    "open": {"open", "launch", "start", "unlatch"},
    "close": {"close", "shut", "exit", "quit"},
    "resources": {"resources", "capabilities", "abilities", "perms", "permissions"},
    "execute": {"execute", "run", "perform", "exec", "do"},
    "commands": {"commands", "instructions", "actions", "cmds"},
    "install": {"install", "setup", "set up", "deploy", "add", "dl"},
    "show": {"show", "display", "present", "print"},
    "error": {"error", "failure", "failures", "fault", "exception", "problem", "err", "bug"},
    "voice": {"voice", "speech", "audio", "mic"},
    "chat": {"chat", "conversation", "message", "msg", "dm"},
    "bot": {"bot", "assistant", "agent", "chatbot"},
    "access": {"access", "interface", "connection", "hookup"},
    "agentically": {"agentically", "agenticallly", "autonomously", "automatically", "auto"},
}

BUILTIN_ANTONYMS: dict[str, set[str]] = {
    "install": {"uninstall", "remove"},
    "open": {"close", "shut"},
    "close": {"open", "launch"},
    "show": {"hide", "conceal"},
    "execute": {"stop", "halt", "cancel"},
}

BLOCKED_TRIGGER_SYNONYMS: dict[str, set[str]] = {
    # Preserve "tv pack" as an identifier phrase in "tv pack library".
    "library": {"pack"},
}


@dataclass
class TriggerLexicon:
    synonyms: dict[str, set[str]] = field(default_factory=dict)
    antonyms: dict[str, set[str]] = field(default_factory=dict)
    definitions: dict[str, list[str]] = field(default_factory=dict)
    source: str = "builtin"

    @classmethod
    def builtin(cls) -> "TriggerLexicon":
        return cls(
            synonyms={canonical: set(words) for canonical, words in CANONICAL_TRIGGERS.items()},
            antonyms={canonical: set(words) for canonical, words in BUILTIN_ANTONYMS.items()},
            definitions={},
            source="builtin",
        )

    @classmethod
    def from_wordnet(
        cls,
        wordnet_dir: str | os.PathLike[str] | None = None,
        thesaurus_path: str | os.PathLike[str] | None = None,
    ) -> "TriggerLexicon":
        lexicon = cls.builtin()
        if wordnet_dir is None:
            wordnet_dir = os.environ.get("SHIPMB_WORDNET_DIR")
        if thesaurus_path is None:
            thesaurus_path = os.environ.get("SHIPMB_THESAURUS_PATH")
        sources = ["builtin"]
        if not wordnet_dir:
            _load_extra_thesaurus(lexicon, thesaurus_path, sources)
            lexicon.source = "+".join(sources)
            return lexicon

        path = Path(wordnet_dir)
        if not path.exists():
            _load_extra_thesaurus(lexicon, thesaurus_path, sources)
            lexicon.source = "+".join(sources)
            return lexicon

        wordnet = _load_wordnet_data(path)
        if not wordnet.synsets:
            _load_extra_thesaurus(lexicon, thesaurus_path, sources)
            lexicon.source = "+".join(sources)
            return lexicon

        for canonical in list(lexicon.synonyms):
            seeds = set(lexicon.synonyms[canonical])
            for seed in seeds | {canonical}:
                for synonym in wordnet.synonyms_for(seed):
                    lexicon.synonyms[canonical].add(synonym)
                for antonym in wordnet.antonyms_for(seed):
                    lexicon.antonyms.setdefault(canonical, set()).add(antonym)
                for definition in wordnet.definitions_for(seed):
                    _add_definition(lexicon.definitions, canonical, definition)
            lexicon.synonyms[canonical].difference_update(BLOCKED_TRIGGER_SYNONYMS.get(canonical, set()))

        sources.append(f"wordnet:{path}")
        _load_extra_thesaurus(lexicon, thesaurus_path, sources)
        lexicon.source = "+".join(sources)
        return lexicon

    def canonical_for(self, word_or_phrase: str) -> str:
        normalized = _normalize_lemma(word_or_phrase)
        for canonical, words in self.synonyms.items():
            if normalized == canonical or normalized in words:
                return canonical
        return normalized

    def normalize_text(self, text: str) -> str:
        normalized = text.lower()
        normalized = _remove_courtesy_shorthand(normalized)
        phrases = sorted(self._phrase_replacements().items(), key=lambda item: len(item[0]), reverse=True)
        for phrase, canonical in phrases:
            normalized = re.sub(rf"\b{re.escape(phrase)}\b", canonical.replace("_", " "), normalized)
        return re.sub(r"[A-Za-z][A-Za-z0-9_']*", lambda match: self.canonical_for(match.group(0)), normalized)

    def trigger_summary(self) -> dict[str, dict[str, list[str]]]:
        return {
            canonical: {
                "synonyms": sorted(words),
                "antonyms": sorted(self.antonyms.get(canonical, set())),
                "definitions": self.definitions.get(canonical, [])[:3],
            }
            for canonical, words in sorted(self.synonyms.items())
        }

    def _phrase_replacements(self) -> dict[str, str]:
        phrases: dict[str, str] = {}
        for canonical, words in self.synonyms.items():
            for word in words:
                if " " in word:
                    phrases[word] = canonical
        return phrases


@dataclass
class _WordNetData:
    synsets: list[set[str]]
    glosses: list[str]
    lemma_to_synsets: dict[str, set[int]]
    antonyms: dict[str, set[str]]

    def synonyms_for(self, lemma: str) -> set[str]:
        normalized = _normalize_lemma(lemma)
        synonyms: set[str] = set()
        for synset_index in self.lemma_to_synsets.get(normalized, set()):
            synonyms.update(self.synsets[synset_index])
        synonyms.discard(normalized)
        return synonyms

    def antonyms_for(self, lemma: str) -> set[str]:
        return set(self.antonyms.get(_normalize_lemma(lemma), set()))

    def definitions_for(self, lemma: str) -> list[str]:
        normalized = _normalize_lemma(lemma)
        definitions: list[str] = []
        seen: set[str] = set()
        for synset_index in self.lemma_to_synsets.get(normalized, set()):
            gloss = self.glosses[synset_index].strip()
            if gloss and gloss not in seen:
                definitions.append(gloss)
                seen.add(gloss)
        return definitions


@lru_cache(maxsize=16)
def default_lexicon(wordnet_dir: str | None = None, thesaurus_path: str | None = None) -> TriggerLexicon:
    if wordnet_dir is None:
        wordnet_dir = os.environ.get("SHIPMB_WORDNET_DIR")
    if thesaurus_path is None:
        thesaurus_path = os.environ.get("SHIPMB_THESAURUS_PATH")
    return TriggerLexicon.from_wordnet(wordnet_dir, thesaurus_path)


def reset_default_lexicon_cache() -> None:
    default_lexicon.cache_clear()


def normalize_trigger_word(word: str, lexicon: TriggerLexicon | None = None) -> str:
    return (lexicon or default_lexicon()).canonical_for(word)


def normalize_trigger_text(text: str, lexicon: TriggerLexicon | None = None) -> str:
    return (lexicon or default_lexicon()).normalize_text(text)


def _load_wordnet_data(path: Path) -> _WordNetData:
    synsets: list[set[str]] = []
    glosses: list[str] = []
    lemma_to_synsets: dict[str, set[int]] = {}
    offset_to_index: dict[tuple[str, str], int] = {}
    pending_antonyms: list[tuple[set[str], str, str]] = []

    for pos in ("noun", "verb", "adj", "adv"):
        data_file = path / f"data.{pos}"
        if not data_file.exists():
            continue
        _read_data_file(data_file, pos[0], synsets, glosses, lemma_to_synsets, offset_to_index, pending_antonyms)

    antonyms: dict[str, set[str]] = {}
    for source_words, target_pos, target_offset in pending_antonyms:
        target_index = offset_to_index.get((target_pos, target_offset))
        if target_index is None:
            continue
        target_words = synsets[target_index]
        for source_word in source_words:
            antonyms.setdefault(source_word, set()).update(target_words)

    return _WordNetData(synsets, glosses, lemma_to_synsets, antonyms)


def _read_data_file(
    data_file: Path,
    fallback_pos: str,
    synsets: list[set[str]],
    glosses: list[str],
    lemma_to_synsets: dict[str, set[int]],
    offset_to_index: dict[tuple[str, str], int],
    pending_antonyms: list[tuple[set[str], str, str]],
) -> None:
    for raw_line in read_text_limited(data_file, MAX_WORDNET_FILE_BYTES, errors="ignore").splitlines():
        if not raw_line or raw_line.startswith("  "):
            continue
        data_part, _, gloss = raw_line.partition("|")
        fields = data_part.split()
        if len(fields) < 5:
            continue
        offset = fields[0]
        synset_pos = fields[2] if len(fields[2]) == 1 else fallback_pos
        try:
            word_count = int(fields[3], 16)
        except ValueError:
            continue
        word_fields_start = 4
        word_fields_end = word_fields_start + word_count * 2
        if len(fields) < word_fields_end + 1:
            continue
        words = {_normalize_lemma(fields[index]) for index in range(word_fields_start, word_fields_end, 2)}
        synset_index = len(synsets)
        synsets.append(words)
        glosses.append(gloss.strip())
        offset_to_index[(synset_pos, offset)] = synset_index
        for word in words:
            lemma_to_synsets.setdefault(word, set()).add(synset_index)

        pointer_index = word_fields_end
        try:
            pointer_count = int(fields[pointer_index])
        except ValueError:
            continue
        pointer_index += 1
        for _ in range(pointer_count):
            if len(fields) < pointer_index + 4:
                break
            symbol, target_offset, target_pos, _source_target = fields[pointer_index : pointer_index + 4]
            pointer_index += 4
            if symbol == "!":
                pending_antonyms.append((words, target_pos, target_offset))


def _normalize_lemma(lemma: str) -> str:
    return lemma.lower().replace("_", " ").strip()


def _add_definition(definitions: dict[str, list[str]], canonical: str, definition: str) -> None:
    if not definition:
        return
    current = definitions.setdefault(canonical, [])
    if definition not in current:
        current.append(definition)


def _load_extra_thesaurus(
    lexicon: TriggerLexicon,
    thesaurus_path: str | os.PathLike[str] | None,
    sources: list[str],
) -> None:
    if not thesaurus_path:
        return
    path = Path(thesaurus_path)
    if not path.exists():
        return
    if path.is_dir():
        for child in sorted(path.iterdir()):
            if child.suffix.lower() in {".json", ".csv", ".tsv", ".txt"}:
                _load_extra_thesaurus_file(lexicon, child)
        sources.append(f"thesaurus:{path}")
        return
    _load_extra_thesaurus_file(lexicon, path)
    sources.append(f"thesaurus:{path}")


def _load_extra_thesaurus_file(lexicon: TriggerLexicon, path: Path) -> None:
    if path.suffix.lower() == ".json":
        _load_json_thesaurus(lexicon, path)
    else:
        _load_text_thesaurus(lexicon, path)


def _load_json_thesaurus(lexicon: TriggerLexicon, path: Path) -> None:
    data = json.loads(read_text_limited(path, MAX_THESAURUS_FILE_BYTES))
    if isinstance(data, dict) and "triggers" in data:
        data = data["triggers"]
    if not isinstance(data, dict):
        return
    for canonical, value in data.items():
        synonyms: list[str] = []
        antonyms: list[str] = []
        definitions: list[str] = []
        if isinstance(value, list):
            synonyms = [str(item) for item in value]
        elif isinstance(value, dict):
            synonyms = [str(item) for item in value.get("synonyms", [])]
            antonyms = [str(item) for item in value.get("antonyms", [])]
            definitions = [str(item) for item in value.get("definitions", [])]
        _merge_trigger_entry(lexicon, str(canonical), synonyms, antonyms, definitions)


def _load_text_thesaurus(lexicon: TriggerLexicon, path: Path) -> None:
    for raw_line in read_text_limited(path, MAX_THESAURUS_FILE_BYTES, errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        separator = "\t" if "\t" in line else "," if "," in line and "=" not in line else "="
        if separator not in line:
            continue
        canonical, raw_aliases = line.split(separator, 1)
        aliases = [alias.strip() for alias in re.split(r"[,|]", raw_aliases) if alias.strip()]
        _merge_trigger_entry(lexicon, canonical.strip(), aliases, [], [])


def _merge_trigger_entry(
    lexicon: TriggerLexicon,
    canonical: str,
    synonyms: list[str],
    antonyms: list[str],
    definitions: list[str],
) -> None:
    canonical = _normalize_lemma(canonical)
    if canonical not in lexicon.synonyms:
        return
    lexicon.synonyms[canonical].update(_normalize_lemma(item) for item in synonyms)
    lexicon.antonyms.setdefault(canonical, set()).update(_normalize_lemma(item) for item in antonyms)
    lexicon.synonyms[canonical].difference_update(BLOCKED_TRIGGER_SYNONYMS.get(canonical, set()))
    for definition in definitions:
        _add_definition(lexicon.definitions, canonical, definition)


def _remove_courtesy_shorthand(text: str) -> str:
    return re.sub(r"\b(?:please|pls|plz)\b", " ", text)
