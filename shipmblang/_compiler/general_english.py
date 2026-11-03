"""Compositional, source-linked English for general computation and media jobs.

No bytecode, runtime, Core or IR imports. Every clause must be consumed.
"""
from __future__ import annotations

import json
import re

from .general_vocabulary import OUTPUT_PATTERN, SUM_NOUNS

GRAMMAR_VERSION = "general-english-0.12"
CATALOG_VERSION = "general-media-0.2"
TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|\d+\.\d+|\d+|[A-Za-z_][A-Za-z_0-9]*|[^\s]')
TYPES = {"integer", "boolean", "text"}
RESERVED = {"it", "them", "true", "false", "and", "or", "not", "if", "then", "otherwise", "end", "let", "set", "show", "for", "each", "while", "be", "to", "in", "of"}
ARTICLES = {"the", "a", "an"}
# Words the parser already consumes as "the WORD of". A field cannot use them.
FIELD_RESERVED = {"sum", "total", "aggregate", "difference", "product", "quotient", "remainder", "length", "number", "result"}
MAX_LAYOUTS = 10000
MAX_FIELDS = 256
NAME_WORDS = r"[a-z_][a-z_0-9]*(?: [a-z_][a-z_0-9]*)*"
FUNCTION = re.compile(r"define (?:a )?function (.+?)(?: with (.+?))? returning (integer|boolean|text|list of integers|list of booleans|list of text)", re.I)
FUNCTION_LOOSE = re.compile(r"define (?:a )?function (.+?)(?: with (.+))? returning (.+)", re.I)
KIND = re.compile(rf"(?:a |an )?({NAME_WORDS}) has (.+)", re.I)
_TYPE_PREFIXES = (
    ("list of integers", "list[integer]"),
    ("list of booleans", "list[boolean]"),
    ("list of texts", "list[text]"),
    ("list of text", "list[text]"),
    ("integer", "integer"),
    ("boolean", "boolean"),
    ("text", "text"),
)


def strip_leading_article(name):
    """Drop one leading the/a/an unless the remaining name would be empty."""
    parts = name.split()
    if len(parts) > 1 and parts[0] in ARTICLES:
        return " ".join(parts[1:])
    return name


def reserved_word(name):
    return next((word for word in name.split() if word in RESERVED), None)


def type_name(value):
    return {"list of integers": "list[integer]", "list of booleans": "list[boolean]", "list of text": "list[text]"}.get(value.lower(), value.lower())


def object_type_name(kind):
    if isinstance(kind, str) and kind.startswith("object[") and kind.endswith("]") and kind.find("[") == kind.rfind("["):
        return kind[7:-1]
    return None


def split_field_phrases(text):
    return [part.strip() for part in re.split(r"\s*,\s*and\s+|\s+and\s+|,\s*", text.strip(), flags=re.I) if part.strip()]


def parse_field_phrase(phrase):
    """Return (name, declared type or None). (None, None) when the phrase is not a field."""
    words = phrase.lower().split()
    if words and words[0] in ARTICLES:
        words = words[1:]
    text = " ".join(words)
    declared = None
    for prefix, kind in _TYPE_PREFIXES:
        if text == prefix:
            return None, None
        if text.startswith(prefix + " "):
            declared = kind
            text = text[len(prefix) + 1:]
            break
    if not text or not re.fullmatch(NAME_WORDS, text):
        return None, None
    return text, declared


def missing_fields_message(kind_name, missing):
    if len(missing) == 1:
        listed = missing[0]
    elif len(missing) == 2:
        listed = f"{missing[0]} and {missing[1]}"
    else:
        listed = ", ".join(missing[:-1]) + ", and " + missing[-1]
    return f"Make a new {kind_name} is missing {listed}. Give every field exactly once."


def returns(body):
    return bool(body) and (body[-1]["kind"] == "Return" or body[-1]["kind"] == "If" and returns(body[-1]["yes"]) and returns(body[-1]["no"]))


class EnglishError(Exception):
    def __init__(self, message, span, *, question=False, code=None):
        self.message, self.span, self.question, self.code = message, span, question, code


def node(kind, span, **fields):
    return {"kind": kind, "span": dict(span), **fields}


def _mask_comments(source):
    """Replace # comments with spaces outside quotes, preserving offsets."""
    chars = list(source)
    quoted = escape = False
    index = 0
    while index < len(chars):
        char = chars[index]
        if quoted:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == "#":
            while index < len(chars) and chars[index] != "\n":
                chars[index] = " "
                index += 1
            continue
        index += 1
    return "".join(chars)


def _has_word_since_terminator(source, index, word):
    """True when `word` occurs after the previous clause terminator and before index."""
    quoted = escape = False
    start = 0
    i = 0
    while i < index:
        char = source[i]
        if quoted:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in ".;:\n?":
            if not (char == "." and i and i + 1 < len(source) and source[i - 1].isdigit() and source[i + 1].isdigit()):
                start = i + 1
        i += 1
    return re.search(rf"\b{re.escape(word)}\b", source[start:index], re.I) is not None


def clauses(source):
    """Sentence/block delimiters outside quoted data, retaining original offsets."""
    # Comments are masked before any split so a hash cannot open or close a clause.
    source = _mask_comments(source)
    # Program wrappers may enclose the whole document or separate paragraphs.
    # Mask delimiters, never trim/rebuild prose: spans index the original source.
    # U+FEFF is not whitespace. A same-length space keeps those spans aligned.
    source = source.replace("\ufeff", " ")
    stripped = source.lstrip()
    if stripped and stripped[0] in {'"', '\u201c'}:
        chars = list(source)
        pos = len(source) - len(stripped)
        while pos < len(source):
            opener = source[pos]
            closer = '"' if opener == '"' else '\u201d'
            chars[pos] = ' '
            start = pos
            pos += 1
            quoted = escape = False
            while pos < len(source):
                char = source[pos]
                if quoted:
                    if escape: escape = False
                    elif char == "\\": escape = True
                    elif char == '"': quoted = False
                elif char == closer:
                    tail = source[pos+1:]
                    gap = len(tail) - len(tail.lstrip())
                    following = pos + 1 + gap
                    # Another wrapper must start a new paragraph, not a clause.
                    separated = tail[:gap].count('\n') >= 2
                    if following == len(source) or (separated and source[following] in {'"', '\u201c'}):
                        chars[pos] = ' '
                        pos = following
                        break
                    if char == '"': quoted = True
                elif char == '"':
                    quoted = True
                pos += 1
            else:
                raise EnglishError("Close the quoted program paragraph; separate quoted paragraphs with a blank line.", {"start": start, "end": len(source)}, question=True)
        source = ''.join(chars)
    # Split coordinated commands only outside quoted data and bracketed values.
    boundaries, depth = [], 0
    for match in TOKEN.finditer(source):
        token = match.group()
        if token.startswith('"'):
            continue
        if token == '[': depth += 1
        if token == ']': depth -= 1
        if depth == 0 and token.lower() in {'and', 'then'}:
            tail = source[match.start():]
            link = re.match(r'(?:and\s+then|and|then)\s+(?=(?:(?:please|pls)\s+)?(?:show|print|display|let|set|change|start|add|subtract|multiply|divide)\b)', tail, re.I)
            if link:
                # "Probe ... and show the duration" is one instruction. Other "and show" splits stay.
                if token.lower() == "and" and re.match(r"and\s+show\s+the\s+duration\b", tail, re.I) and _has_word_since_terminator(source, match.start(), "probe"):
                    continue
                start_link = match.start()
                if start_link and source[start_link-1] == ',': start_link -= 1
                elif source[:start_link].rstrip().endswith(','):
                    start_link = len(source[:start_link].rstrip()) - 1
                boundaries.append((start_link, match.start()+link.end()))
    for a, b in reversed(boundaries):
        source = source[:a] + ';' + ' '*(b-a-1) + source[b:]
    result, start, quoted, escape = [], 0, False, False
    for i, char in enumerate(source):
        if quoted:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in ".;:\n?":
            # A decimal literal is unsupported, but must not become two statements.
            if char == "." and i and i + 1 < len(source) and source[i-1].isdigit() and source[i+1].isdigit():
                continue
            if source[start:i].strip():
                left = start + len(source[start:i]) - len(source[start:i].lstrip())
                right = i - len(source[start:i]) + len(source[start:i].rstrip())
                result.append((source[left:right], {"start": left, "end": right}))
            start = i + 1
    if quoted:
        raise EnglishError("Close the quoted text before continuing.", {"start": start, "end": len(source)}, question=True)
    if source[start:].strip():
        left = start + len(source[start:]) - len(source[start:].lstrip())
        result.append((source[left:].rstrip(), {"start": left, "end": len(source.rstrip())}))
    return result


class Expressions:
    def __init__(self, text, offset, owner):
        self.tokens = [(m.group(), offset + m.start(), offset + m.end()) for m in TOKEN.finditer(text) if m.group() != "\ufeff"]
        self.at, self.owner = 0, owner
        self.span = {"start": offset, "end": offset + len(text)}

    def take(self, *words):
        if [t[0].lower() for t in self.tokens[self.at:self.at+len(words)]] == list(words):
            self.at += len(words)
            return True
        return False

    def fail(self, message, question=False, code=None):
        span = {"start": self.tokens[self.at][1], "end": self.tokens[self.at][2]} if self.at < len(self.tokens) else self.span
        raise EnglishError(message, span, question=question, code=code)

    def parse(self):
        value = self.expression()
        if self.at != len(self.tokens):
            self.fail("This expression has unconsumed wording; state its grouping or operation explicitly.", question=True)
        return value

    def expression(self, minimum=0):
        left = self.atom()
        infix_arithmetic = False
        operators = [
            (("is", "greater", "than", "or", "equal", "to"), "greater_equal", 3),
            (("is", "less", "than", "or", "equal", "to"), "less_equal", 3),
            (("is", "not", "equal", "to"), "not_equal", 3),
            (("is", "equal", "to"), "equal", 3),
            (("is", "greater", "than"), "greater", 3),
            (("is", "less", "than"), "less", 3),
            (("is", "at", "least"), "greater_equal", 3),
            (("is", "at", "most"), "less_equal", 3),
            (("equals",), "equal", 3),
            (("plus",), "add", 4), (("minus",), "subtract", 4),
            (("times",), "multiply", 5), (("divided", "by"), "divide", 5),
            (("and",), "and", 2), (("or",), "or", 1),
        ]
        while True:
            found = False
            for words, operator, priority in operators:
                if priority >= minimum and self.take(*words):
                    right = self.expression(priority + 1)
                    # Text concatenation chains; integer, times, and divide still need grouping.
                    text_plus = operator == "add" and left["type"] == "text" and right["type"] == "text"
                    if priority >= 4 and not text_plus:
                        if infix_arithmetic or (right["kind"] == "Binary" and right["operator"] in {"add", "subtract", "multiply", "divide", "modulo"} and not right.get("explicit_group")):
                            self.fail("State arithmetic grouping explicitly using parentheses or 'the sum/product of'.", question=True)
                        infix_arithmetic = True
                    elif text_plus and infix_arithmetic:
                        self.fail("State arithmetic grouping explicitly using parentheses or 'the sum/product of'.", question=True)
                    left = self.binary(operator, left, right)
                    found = True
                    break
            if not found:
                return left

    def binary(self, operator, left, right):
        ltype, rtype = left["type"], right["type"]
        if object_type_name(ltype) or object_type_name(rtype):
            self.fail("Phase 1 does not support comparing objects.", code="SMBG113")
        if operator in {"and", "or"}:
            valid, output = ltype == rtype == "boolean", "boolean"
        elif operator in {"equal", "not_equal"}:
            valid, output = ltype == rtype, "boolean"
        elif operator in {"greater", "less", "greater_equal", "less_equal"}:
            valid, output = ltype == rtype and ltype in {"integer", "text"}, "boolean"
        else:
            valid = ltype == rtype == "integer" or operator == "add" and ltype == rtype == "text"
            output = ltype
        if not valid:
            self.fail(f"{operator} does not accept {ltype} and {rtype}; no implicit conversion is performed.")
        return node("Binary", {"start": left["span"]["start"], "end": right["span"]["end"]}, operator=operator, left=left, right=right, type=output)

    def atom(self):
        begin = self.at
        if self.at >= len(self.tokens):
            self.fail("Supply a value or a declared name.", question=True)
        if self.take("("):
            value = self.expression()
            if not self.take(")"):
                self.fail("Close the grouped expression.", question=True)
            value["explicit_group"] = True
            return value
        if self.take("not"):
            operand = self.expression(3)
            if operand["type"] != "boolean":
                self.fail("Not requires a boolean expression.")
            return node("Unary", self.range(begin), operator="not", operand=operand, type="boolean")
        if self.take("negative") or self.take("-"):
            operand = self.atom()
            if operand["type"] != "integer":
                self.fail("Negative requires an integer.")
            return node("Unary", self.range(begin), operator="negate", operand=operand, type="integer")
        from .vision_english import parse_vision_expression
        vision = parse_vision_expression(self, begin)
        if vision is not None:
            return vision
        self.take("the")
        if self.at < len(self.tokens) and self.tokens[self.at][0].lower() in {"duration", "position", "width", "height"}:
            from .vlc_english import parse_player_property
            player_property = parse_player_property(self, begin)
            if player_property is not None:
                return player_property
        if self.take("vlc"):
            from .vlc_english import parse_query
            return parse_query(self, begin)
        if self.take("result", "of"):
            for name, signature in sorted(self.owner.functions.items(), key=lambda pair: -len(pair[0])):
                if not self.take(*name.split()):
                    continue
                arguments = []
                if signature["parameters"] and not self.take("with"):
                    self.fail("Supply function arguments after 'with'.", question=True)
                for i, parameter in enumerate(signature["parameters"]):
                    if i and not self.take("and"):
                        self.fail("Separate function arguments with 'and'.", question=True)
                    argument = self.expression(4)
                    if argument["type"] != parameter["type"]:
                        self.fail(f"Parameter '{parameter['name']}' requires {parameter['type']}.")
                    arguments.append(argument)
                return node("Call", self.range(begin), function=signature["id"], arguments=arguments, argument_types=[p["type"] for p in signature["parameters"]], type=signature["return_type"])
            self.fail("Name a declared function after 'the result of'.", question=True)
        for word, operator, separator in tuple((word, "add", "and") for word in SUM_NOUNS) + (("difference", "subtract", "and"), ("product", "multiply", "and"), ("quotient", "divide", "and"), ("remainder", "modulo", "and")):
            if self.take(word, "of"):
                left = self.expression(4)
                if not self.take(separator):
                    self.fail(f"State both operands: {word} of one value and another.", question=True)
                right = self.expression(4)
                if word in {"total", "aggregate"} and (left['type'] != 'integer' or right['type'] != 'integer'):
                    self.fail("This aggregation sense requires two integers; specify the intended operation.", question=True)
                value = self.binary(operator, left, right)
                value["explicit_group"] = True
                return value
        if self.take("number", "of", "items", "in"):
            value = self.atom()
            if not value["type"].startswith("list["):
                self.fail("Length requires a list.")
            return node("Length", self.range(begin), value=value, type="integer")
        if self.take("length", "of"):
            value = self.atom()
            if value["type"] != "text" and not value["type"].startswith("list["):
                self.fail("Length requires text or a list.")
            return node("Length", self.range(begin), value=value, type="integer")
        segmented = self.text_segment(begin)
        if segmented is not None:
            return segmented
        if self.take("first", "item", "in") or self.take("last", "item", "in"):
            phrase = [token[0].lower() for token in self.tokens[begin:self.at]]
            last = "last" in phrase
            value = self.atom()
            if not value["type"].startswith("list["):
                self.fail("List indexing requires a list.")
            if last:
                length = node("Length", {"start": value["span"]["start"], "end": value["span"]["end"]}, value=value, type="integer")
                index = node("Binary", self.range(begin), operator="subtract", type="integer", explicit_group=True,
                             left=length, right=node("Literal", self.range(begin), value=1, type="integer"))
            else:
                index = node("Literal", self.range(begin), value=0, type="integer")
            return node("Index", self.range(begin), value=value, index=index, type=value["type"][5:-1])
        if self.take("item", "number"):
            number = self.expression(3)
            if not self.take("in"):
                self.fail("Specify the list after 'in'.", question=True)
            value = self.atom()
            if number["type"] != "integer" or not value["type"].startswith("list["):
                self.fail("List indexing requires an integer item number and a list.")
            index = node("Binary", self.range(begin), operator="subtract", type="integer", explicit_group=True,
                         left=number, right=node("Literal", self.range(begin), value=1, type="integer"))
            return node("Index", self.range(begin), value=value, index=index, type=value["type"][5:-1])
        if self.take("item", "at", "index"):
            index = self.expression(3)
            if not self.take("in"):
                self.fail("Specify the list after 'in'.", question=True)
            value = self.atom()
            if index["type"] != "integer" or not value["type"].startswith("list["):
                self.fail("List indexing requires an integer index and a list.")
            return node("Index", self.range(begin), value=value, index=index, type=value["type"][5:-1])
        if self.take("empty", "list", "of"):
            element = self.element_type()
            return node("List", self.range(begin), values=[], type=f"list[{element}]")
        if self.take("list", "of"):
            element = self.element_type()
            values = []
            if self.at == len(self.tokens):
                self.fail("Specify list values or say 'empty list'.", question=True)
            while True:
                value = self.expression(3)
                if value["type"] != element:
                    self.fail(f"List values must all be {element}.")
                values.append(value)
                if len(values) > 10000:
                    self.fail("List literal exceeds the 10000-item limit.")
                if self.take(","):
                    self.take("and")
                    continue
                # A bare "and" may start the next field of "make ... with".
                saved = self.at
                if not self.take("and"):
                    break
                restart = self.at
                try:
                    nxt = self.expression(3)
                except EnglishError:
                    self.at = saved
                    break
                if nxt["type"] != element:
                    self.at = saved
                    break
                self.at = restart
            return node("List", self.range(begin), values=values, type=f"list[{element}]")
        accessed = self.field_get(begin)
        if accessed is not None:
            return accessed
        text = self.tokens[self.at][0]
        if text.startswith('"'):
            try:
                value = json.loads(text)
                if len(value.encode("utf-8")) > 1000000:
                    self.fail("Text literal exceeds the 1000000-byte limit.")
            except ValueError:
                self.fail("Use a complete double-quoted text value.")
            self.at += 1
            return node("Literal", self.range(begin), value=value, type="text")
        if re.fullmatch(r"\d+\.\d+", text):
            self.fail("Decimals are unsupported; use integers.", question=True)
        if text.isdecimal():
            if len(text) > 1233:
                self.fail("Integer literal exceeds the 4096-bit limit.")
            self.at += 1
            value = int(text)
            if value.bit_length() > 4096:
                self.fail("Integer literal exceeds the 4096-bit limit.")
            return node("Literal", self.range(begin), value=value, type="integer")
        if text.lower() in {"true", "false"}:
            self.at += 1
            return node("Literal", self.range(begin), value=text.lower() == "true", type="boolean")
        # Longest declared multiword name wins; there is no global word replacement.
        # a/an is an article only when the words after it are a declared name.
        saved = self.at
        if self.take("a") or self.take("an"):
            named = self.match_declared_name(begin)
            if named is not None:
                return named
            self.at = saved
        named = self.match_declared_name(begin)
        if named is not None:
            return named
        if text.lower() in {"it", "them"}:
            candidates = list(self.owner.visible().values())
            if text.lower() == "them":
                candidates = [s for s in candidates if s["type"].startswith("list[")]
            if len(candidates) == 1:
                self.at += 1
                symbol = candidates[0]
                return node("Name", self.range(begin), slot=symbol["id"], name=symbol["name"], type=symbol["type"])
            self.fail("Which declared value does this reference mean? Use its name.", question=True)
        self.fail(f"'{text}' is not a declared value. Declare it or clarify the intended value.", question=True)

    def field_get(self, begin):
        names = sorted({field["name"] for kind in self.owner.classes.values() for field in kind["fields"]}, key=len, reverse=True)
        saved = self.at
        for name in names:
            self.at = saved
            if not self.take(*name.split()) or not self.take("of"):
                continue
            value = self.atom()
            kind_name = object_type_name(value["type"])
            if kind_name is None:
                self.fail("Field access requires an object.")
            kind = self.owner.classes.get(kind_name)
            if kind is None:
                self.fail(f"There is no kind named '{kind_name}'. Define it first: A {kind_name} has ...")
            if kind_name not in self.owner.ready:
                self.fail(f"Define '{kind_name}' before using it. Say 'A {kind_name} has ...' first.")
            field = next((item for item in kind["fields"] if item["name"] == name), None)
            if field is None:
                self.fail(f"Class '{kind_name}' has no field named '{name}'.", code="SMBG111")
            if not field["type"]:
                self.fail(f"Make a {kind_name} before reading field '{name}'.")
            kind["used"] = True
            return node("FieldGet", self.range(begin), value=value, layout=kind["id"], offset=field["offset"], type=field["type"])
        self.at = saved
        return None

    def initializers(self, kind):
        fields = {field["name"]: field for field in kind["fields"]}
        names = sorted(fields, key=len, reverse=True)
        given, order = {}, []
        if self.at >= len(self.tokens):
            self.fail("Give every field of the new value.", question=True)
        while True:
            if order and not self.take("and"):
                break
            saved = self.at
            matched = None
            for name in names:
                self.at = saved
                if self.take(*name.split()):
                    matched = name
                    break
            if matched is None:
                word = self.tokens[self.at][0].lower() if self.at < len(self.tokens) else "value"
                self.fail(f"Class '{kind['name']}' has no field named '{word}'.", code="SMBG111")
            if matched in given:
                span = {"start": self.tokens[saved][1], "end": self.tokens[self.at - 1][2]}
                raise EnglishError(f"Field '{matched}' is given twice in this new {kind['name']}.", span, code="SMBG112")
            self.take("equal", "to")
            value = self.expression(4)
            if object_type_name(value["type"]):
                self.fail("Phase 1 does not support objects as fields of objects.", code="SMBG113")
            field = fields[matched]
            if field["type"] is None:
                field["type"] = value["type"]
            elif field["type"] != value["type"]:
                self.fail(f"Field '{matched}' of class '{kind['name']}' is {field['type']}, not {value['type']}.")
            given[matched] = value
            order.append(field["offset"])
        if self.at != len(self.tokens):
            self.fail("This expression has unconsumed wording; state its grouping or operation explicitly.", question=True)
        missing = [field["name"] for field in kind["fields"] if field["name"] not in given]
        return given, order, missing

    def match_declared_name(self, begin):
        for name, symbol in sorted(self.owner.visible().items(), key=lambda pair: -len(pair[0])):
            if self.take(*name.split()):
                return node("Name", self.range(begin), slot=symbol["id"], name=name, type=symbol["type"])
        return None

    def text_segment(self, begin):
        def text_value():
            value = self.atom()
            if value["type"] != "text":
                self.fail("This splitter requires text.")
            return value

        def integer_value(label):
            value = self.expression(4)
            if value["type"] != "integer":
                self.fail(f"The {label} must be an integer.")
            return value

        if self.take("graphemes", "of"):
            return node("TextSeg", self.range(begin), operation="graphemes", arguments=[text_value()], type="list[text]")
        operation = "words" if self.take("words", "of") else "sentences" if self.take("sentences", "of") else None
        if operation:
            return node("TextSeg", self.range(begin), operation=operation, arguments=[text_value(), self.language_suffix(begin)], type="list[text]")
        if self.take("chunks", "of"):
            subject = text_value()
            if not self.take("with", "byte", "cap"):
                self.fail("State the byte cap after 'with byte cap'.", question=True)
            byte_cap = integer_value("byte cap")
            if self.take("and", "word", "cap"):
                word_cap = integer_value("word cap")
                return node("TextSeg", self.range(begin), operation="chunks_words",
                            arguments=[subject, byte_cap, word_cap, self.language_suffix(begin)], type="list[text]")
            return node("TextSeg", self.range(begin), operation="chunks",
                        arguments=[subject, byte_cap, self.language_suffix(begin)], type="list[text]")
        if self.take("frames", "of"):
            subject = text_value()
            if not self.take("for", "message"):
                self.fail("State the message id after 'for message'.", question=True)
            return node("TextSeg", self.range(begin), operation="frames",
                        arguments=[subject, integer_value("message id")], type="list[text]")
        if self.take("verified", "text", "of"):
            frames = self.atom()
            if frames["type"] != "list[text]":
                self.fail("Frame verification requires a list of text.")
            return node("TextSeg", self.range(begin), operation="unframe", arguments=[frames], type="text")
        return None

    def language_suffix(self, begin):
        if not self.take("in"):
            return node("Literal", self.range(begin), value="", type="text")
        language = self.atom()
        if language["type"] != "text":
            self.fail('Name the language with text, for example "en".')
        return language

    def element_type(self):
        saved = self.at
        for name in sorted(self.owner.classes, key=len, reverse=True):
            if self.take(*name.split()):
                span = {"start": self.tokens[saved][1], "end": self.tokens[self.at - 1][2]}
                raise EnglishError("Phase 1 does not support objects as list elements.", span, code="SMBG113")
        if self.take("object"):
            span = {"start": self.tokens[saved][1], "end": self.tokens[self.at - 1][2]}
            raise EnglishError("Phase 1 does not support objects as list elements.", span, code="SMBG113")
        self.at = saved
        for word, kind in (("integers", "integer"), ("booleans", "boolean"), ("texts", "text"), ("text", "text")):
            if self.take(word):
                return kind
        self.fail("Specify integers, booleans, or text for the list.")

    def range(self, begin):
        return {"start": self.tokens[begin][1], "end": self.tokens[self.at - 1][2]}


class Parser:
    def __init__(self, source):
        self.source, self.clauses, self.at = source, clauses(source), 0
        self.scopes, self.symbols = [{}], []
        self.functions, self.function_nodes, self.return_type = {}, [], None
        self.classes, self.class_order, self.ready = {}, [], set()
        self._collect_classes()
        # Collect signatures before resolving any function call (including recursion).
        for text, span in self.clauses:
            stripped = re.sub(r"^(?:(?:could|would|can) you\s+(?:(?:please|pls)\s+)?|I want you to\s+(?:(?:please|pls)\s+)?|(?:please|pls)\s+)", "", text, flags=re.I)
            match = FUNCTION.fullmatch(stripped)
            if not match:
                loose = FUNCTION_LOOSE.fullmatch(stripped)
                if loose and (self._mentions_kind(loose.group(3)) or (loose.group(2) and self._mentions_kind(loose.group(2)))):
                    raise EnglishError("Phase 1 does not support objects as parameters or results.", span, code="SMBG113")
                continue
            name, params, result_type = match.groups()
            name = name.lower()
            if name in self.classes:
                raise EnglishError(f"Class '{name}' is already defined.", span, code="SMBG112")
            reserved = reserved_word(name)
            if reserved is not None:
                raise EnglishError(f"Function names must be distinct explicit names without reserved words. '{reserved}' is reserved.", span)
            if name in self.functions or not re.fullmatch(r"[a-z_][a-z_0-9]*(?: [a-z_][a-z_0-9]*)*", name):
                raise EnglishError("Function names must be distinct explicit names without reserved words.", span)
            parameters = []
            for definition in re.split(r"\s+and\s+", params, flags=re.I) if params else []:
                param = re.fullmatch(r"(integer|boolean|text|list of integers|list of booleans|list of text) parameter (.+)", definition, re.I)
                if not param:
                    if self._mentions_kind(definition):
                        raise EnglishError("Phase 1 does not support objects as parameters or results.", span, code="SMBG113")
                    raise EnglishError("Declare each typed parameter, for example 'integer parameter amount'.", span, question=True)
                parameters.append({"name": param[2].lower(), "type": type_name(param[1])})
            self.functions[name] = {"id": len(self.functions), "name": name, "parameters": parameters, "return_type": type_name(result_type)}

    def _polite(self, text):
        return re.sub(r"^(?:(?:could|would|can) you\s+(?:(?:please|pls)\s+)?|I want you to\s+(?:(?:please|pls)\s+)?|(?:please|pls)\s+)", "", text, flags=re.I)

    def _mentions_kind(self, text):
        lowered = text.lower()
        if re.search(r"\bobject\b", lowered):
            return True
        return any(re.search(rf"\b{re.escape(name)}\b", lowered) for name in self.classes)

    def _collect_classes(self):
        for text, span in self.clauses:
            match = KIND.fullmatch(self._polite(text))
            if not match:
                continue
            name = match.group(1).lower()
            reserved = reserved_word(name)
            if reserved is not None:
                raise EnglishError(f"Kind names must be distinct explicit names without reserved words. '{reserved}' is reserved.", span)
            if name in self.classes or name in self.functions or not re.fullmatch(NAME_WORDS, name):
                raise EnglishError(f"Class '{name}' is already defined." if name in self.classes or name in self.functions else "Kind names must be distinct explicit names without reserved words.", span, code="SMBG112" if name in self.classes or name in self.functions else None)
            if len(self.class_order) >= MAX_LAYOUTS:
                raise EnglishError("Program exceeds the supported number of layouts.", span)
            phrases = split_field_phrases(match.group(2))
            if not phrases or len(phrases) > MAX_FIELDS:
                raise EnglishError("A kind needs between 1 and 256 fields.", span)
            fields, seen = [], set()
            for phrase in phrases:
                field_name, declared = parse_field_phrase(phrase)
                if field_name is None:
                    raise EnglishError("Use an explicit field name without reserved grammar words.", span)
                field_reserved = reserved_word(field_name)
                if field_reserved is not None:
                    raise EnglishError(f"Use an explicit field name without reserved grammar words. '{field_reserved}' is reserved.", span)
                blocked = next((word for word in field_name.split() if word in FIELD_RESERVED), None)
                if blocked is not None:
                    raise EnglishError(f"Field name '{blocked}' is reserved for arithmetic or of phrases; rename the field.", span, code="SMBG110")
                if field_name in seen:
                    raise EnglishError(f"Field '{field_name}' is declared twice on class '{name}'.", span, code="SMBG112")
                seen.add(field_name)
                fields.append({"name": field_name, "type": declared, "offset": len(fields)})
            self.classes[name] = {"id": len(self.class_order), "name": name, "fields": fields, "used": False, "span": span}
            self.class_order.append(name)

    def require_kind(self, name, span):
        kind = self.classes.get(name)
        if kind is None:
            raise EnglishError(f"There is no kind named '{name}'. Define it first: A {name} has ...", span)
        if name not in self.ready:
            raise EnglishError(f"Define '{name}' before using it. Say 'A {name} has ...' first.", span)
        return kind

    def published_layouts(self):
        published = []
        for name in self.class_order:
            kind = self.classes[name]
            missing = [field["name"] for field in kind["fields"] if not field["type"]]
            if missing:
                if kind["used"]:
                    raise EnglishError(f"Give every field of {name} a type, or make a {name} that sets {', '.join(missing)}.", kind["span"], question=True)
                continue
            published.append({"id": kind["id"], "name": kind["name"], "fields": [{"name": field["name"], "type": field["type"], "offset": field["offset"]} for field in kind["fields"]]})
        return published

    def visible(self):
        return {key: value for scope in self.scopes for key, value in scope.items()}

    def resolve_reference(self, name, span):
        name = strip_leading_article(name.lower())
        if name in {"it", "them"}:
            candidates = list(self.visible().values())
            if name == "them":
                candidates = [item for item in candidates if item["type"].startswith("list[")]
            if len(candidates) != 1:
                raise EnglishError("Which declared value does this reference mean? Use its name.", span, question=True)
            return candidates[0]
        return self.visible().get(name)

    def declare(self, name, kind, mutable, span):
        name = strip_leading_article(name.lower())
        reserved = reserved_word(name)
        if reserved is not None or not re.fullmatch(r"[a-z_][a-z_0-9]*(?: [a-z_][a-z_0-9]*)*", name):
            if reserved is not None:
                raise EnglishError(f"Use an explicit name without reserved grammar words. '{reserved}' is reserved.", span)
            raise EnglishError("Use an explicit name without reserved grammar words.", span)
        if name in self.visible():
            raise EnglishError(f"'{name}' is already declared; shadowing is not permitted.", span)
        symbol = {"id": len(self.symbols), "name": name, "type": kind, "mutable": mutable}
        self.symbols.append(symbol)
        self.scopes[-1][name] = symbol
        return symbol

    def expr(self, text, offset):
        return Expressions(text, offset, self).parse()

    def hidden_integer(self, prefix):
        slot = len(self.symbols)
        symbol = {"id": slot, "name": f"${prefix}{slot}", "type": "integer", "mutable": True}
        self.symbols.append(symbol)
        return symbol

    def conditional(self, condition, span, depth, *, close):
        self.scopes.append({})
        yes = self.block("condition", depth + 1)
        yes_slots = [symbol["id"] for symbol in self.scopes.pop().values()]
        no, no_slots = [], []
        if self.at < len(self.clauses):
            text, branch_span = self.clauses[self.at]
            nested = re.fullmatch(r"otherwise if (.+?) then", text, re.I)
            if nested:
                self.at += 1
                branch = self.expr(nested[1], branch_span["start"] + nested.start(1))
                if branch["type"] != "boolean":
                    raise EnglishError("If requires a boolean condition.", branch_span)
                no = [self.conditional(branch, branch_span, depth + 1, close=False)]
            elif text.lower() in {"otherwise", "else"}:
                self.at += 1
                self.scopes.append({})
                no = self.block("condition", depth + 1)
                no_slots = [symbol["id"] for symbol in self.scopes.pop().values()]
        if close:
            self.finish({"end the condition", "end if"}, span)
        return node("If", span, condition=condition, yes=yes, no=no, yes_slots=yes_slots, no_slots=no_slots)

    def block(self, end=None, depth=0):
        if depth > 64:
            raise EnglishError("Block nesting exceeds 64 levels.", {"start": 0, "end": len(self.source)})
        body = []
        while self.at < len(self.clauses):
            text, span = self.clauses[self.at]
            lower = text.lower()
            if lower in {"otherwise", "else", "end the condition", "end if", "end the loop", "end loop", "end the function", "end function"} or re.fullmatch(r"otherwise if .+ then", lower):
                if end is None:
                    raise EnglishError("This block ending has no matching opening.", span, question=True)
                return body
            if returns(body):
                raise EnglishError("This statement cannot run because the preceding paths return.", span)
            self.at += 1
            polite = re.match(r"(?:(?:could|would|can) you\s+(?:(?:please|pls)\s+)?|I want you to\s+(?:(?:please|pls)\s+)?|(?:please|pls)\s+)", text, re.I)
            if polite:
                text = text[polite.end():]
                span = {"start": span["start"] + polite.end(), "end": span["end"]}
            if re.match(r'(?:run ffmpeg\b|convert\b|transcode\b|extract audio\b|resize\b|trim\b|probe\b)', text, re.I):
                from .media_english import parse_media
                media = parse_media(self, text, span)
                if media is not None:
                    body.append(media)
                    continue
            from .vision_english import parse_vision_clause
            vision = parse_vision_clause(self, text, span)
            if vision is not None:
                body.append(node("Show", span, value=vision))
                continue
            from .vlc_english import parse_vlc
            vlc = parse_vlc(self,text,span)
            if vlc is not None:
                body.append(vlc)
                continue
            # Explicit two-operand addition with a requested output, not an
            # implicit update. Parse both operands without rewriting offsets.
            addition = re.fullmatch(r"add (.+?) and (.+?)(?: together)? and tell me the result", text, re.I)
            if addition:
                left = self.expr(addition[1], span['start'] + addition.start(1))
                right = self.expr(addition[2], span['start'] + addition.start(2))
                if left['type'] != 'integer' or right['type'] != 'integer':
                    raise EnglishError('Arithmetic addition requires two integers.', span)
                value = node('Binary', span, operator='add', left=left, right=right, type='integer', explicit_group=True)
                body.append(node('Show', span, value=value))
                continue
            match = re.fullmatch(r"start with (?:(.+?) at )?(.+)", text, re.I)
            if match:
                value = self.expr(match[2], span['start'] + match.start(2))
                symbol = self.declare(match[1] or 'result', value['type'], True, span)
                body.append(node('Declare', span, slot=symbol['id'], value=value))
                continue
            implicit = re.fullmatch(r"(add|subtract) (.+)", text, re.I)
            match = re.fullmatch(r"(add|subtract) (.+?) (to|from) (.+)|(multiply|divide) (.+?) by (.+)", text, re.I)
            if implicit and not match:
                parsed = None
                parse_error = None
                try:
                    parsed = self.expr(implicit[2], span['start'] + implicit.start(2))
                except EnglishError as error:
                    parse_error = error
                integer_operand = parse_error is None and parsed is not None and parsed['type'] == 'integer'
                candidates = [s for s in self.visible().values() if s['mutable'] and s['type'] == 'integer']
                if not integer_operand:
                    # A prose operand is not a missing integer target; keep asking.
                    if len(candidates) == 1:
                        if parse_error is not None:
                            raise parse_error
                        raise EnglishError('Arithmetic updates require an integer.', span)
                    raise EnglishError(
                        "This is not an integer update. To filter a list, use for each: "
                        "Let values be the list of integers 2, 5, 8, 11. "
                        "For each value in values: If (the remainder of value and 2) equals 1 then: "
                        "Add value to total. End the condition. End the loop.",
                        span,
                        question=True,
                    )
                if len(candidates) != 1:
                    raise EnglishError('Name the arithmetic target explicitly.', span, question=True)
                symbol = candidates[0]
                value = node('Binary', span, operator=implicit[1].lower(), left=node('Name', span, slot=symbol['id'], type='integer'), right=parsed, type='integer')
                body.append(node('Assign', span, slot=symbol['id'], value=value))
                continue
            if match:
                if match[1]:
                    verb, rhs, prep, name = match.group(1, 2, 3, 4)
                    if (verb.lower(), prep.lower()) not in {('add','to'),('subtract','from')}:
                        raise EnglishError('Use add to or subtract from explicitly.', span, question=True)
                    offset = span['start'] + match.start(2)
                else:
                    verb, name, rhs = match.group(5, 6, 7)
                    offset = span['start'] + match.start(7)
                symbol = self.resolve_reference(name, span)
                if not symbol:
                    raise EnglishError('Declare the arithmetic target first.', span, question=True)
                if not symbol['mutable']:
                    raise EnglishError('The arithmetic target must be mutable.', span)
                right = self.expr(rhs, offset)
                if symbol['type'] != 'integer' or right['type'] != 'integer':
                    raise EnglishError('These arithmetic updates require integers.', span)
                left = node('Name', span, slot=symbol['id'], type=symbol['type'])
                value = node('Binary', span, operator={'add':'add','subtract':'subtract','multiply':'multiply','divide':'divide'}[verb.lower()], left=left, right=right, type='integer')
                body.append(node('Assign', span, slot=symbol['id'], value=value))
                continue
            match = FUNCTION.fullmatch(text)
            if match:
                if depth or self.return_type:
                    raise EnglishError("Functions must be declared at program scope; closures are not supported.", span)
                signature = self.functions[match[1].lower()]
                function = object.__new__(Parser)
                function.source, function.clauses, function.at = self.source, self.clauses, self.at
                function.scopes, function.symbols = [{}], []
                function.functions, function.function_nodes = self.functions, []
                function.classes, function.class_order, function.ready = self.classes, self.class_order, self.ready
                function.return_type = signature["return_type"]
                parameter_slots = [function.declare(p["name"], p["type"], False, span)["id"] for p in signature["parameters"]]
                function_body = function.block("function", depth+1)
                function.finish({"end the function", "end function"}, span)
                self.at = function.at
                if not returns(function_body):
                    raise EnglishError(f"Function '{signature['name']}' must return a {signature['return_type']} on every path.", span)
                self.function_nodes.append(node("Function", span, id=signature["id"], name=signature["name"], parameter_slots=parameter_slots,
                                                return_type=signature["return_type"], locals=function.symbols, body=function_body))
                continue
            match = re.fullmatch(r"return (.+)", text, re.I)
            if match:
                if self.return_type is None:
                    raise EnglishError("Return is allowed only within a function.", span)
                value = self.expr(match[1], span["start"] + 7)
                if value["type"] != self.return_type:
                    raise EnglishError(f"The returned value must be {self.return_type}.", span)
                body.append(node("Return", span, value=value))
                continue
            match = re.fullmatch(r"(?:let|define) (.+?) be (.+)", text, re.I)
            if match:
                name, rhs = match.groups()
                mutable, declared_type = False, None
                prefix = re.match(r"(?:a |an )?(mutable )?(integer|boolean|text)(?: with value| equal to) (.+)", rhs, re.I)
                list_form = None if prefix else re.fullmatch(
                    r"(?:a |an )?(mutable )?(list of integers|list of booleans|list of texts|list of text)(?: (?:with value|equal to) (.+))?",
                    rhs, re.I)
                if prefix:
                    mutable = bool(prefix[1])
                    declared_type, rhs = prefix[2].lower(), prefix[3]
                elif list_form:
                    mutable = bool(list_form[1])
                    kind = list_form[2].lower()
                    declared_type = type_name("list of text" if kind == "list of texts" else kind)
                    if list_form[3] is None:
                        value = node("List", span, values=[], type=declared_type)
                        symbol = self.declare(name, value["type"], mutable, span)
                        body.append(node("Declare", span, slot=symbol["id"], value=value))
                        continue
                    rhs = list_form[3]
                elif re.match(r"(?:a )?mutable\b", rhs, re.I):
                    raise EnglishError("Declare a mutable type and its initial value explicitly.", span, question=True)
                offset = span["end"] - len(rhs)
                value = self.expr(rhs, offset)
                if declared_type and declared_type != value["type"]:
                    raise EnglishError("The initial value does not match the declared type.", span)
                symbol = self.declare(name, value["type"], mutable, span)
                body.append(node("Declare", span, slot=symbol["id"], value=value))
                continue
            match = re.fullmatch(r"(?:set|change) the (.+?) of (.+?) to (.+)", text, re.I)
            if match and not re.match(r"set vlc\b", lower):
                field_name, target_name, rhs = match.group(1).lower(), match.group(2), match.group(3)
                symbol = self.resolve_reference(target_name, span)
                if not symbol:
                    raise EnglishError("Declare the assignment target first.", span, question=True)
                kind_name = object_type_name(symbol["type"])
                if kind_name is None:
                    raise EnglishError("Field update requires an object.", span)
                kind = self.require_kind(kind_name, span)
                field = next((item for item in kind["fields"] if item["name"] == field_name), None)
                if field is None:
                    raise EnglishError(f"Class '{kind_name}' has no field named '{field_name}'.", span, code="SMBG111")
                if not symbol["mutable"]:
                    raise EnglishError(f"'{symbol['name']}' is immutable; declare it mutable to change it.", span)
                if not field["type"]:
                    raise EnglishError(f"Make a {kind_name} before reading field '{field_name}'.", span)
                value = self.expr(rhs, span["end"] - len(rhs))
                if object_type_name(value["type"]):
                    raise EnglishError("Phase 1 does not support objects as fields of objects.", span, code="SMBG113")
                if value["type"] != field["type"]:
                    raise EnglishError(f"Field '{field_name}' of class '{kind_name}' is {field['type']}, not {value['type']}.", span)
                kind["used"] = True
                body.append(node("UpdateField", span, slot=symbol["id"], layout=kind["id"], offset=field["offset"],
                                  field_types=[item["type"] for item in kind["fields"]], value=value))
                continue
            match = re.fullmatch(r"(?:set|change) (.+?) to (.+)", text, re.I)
            if match:
                symbol = self.resolve_reference(match[1], span)
                if not symbol:
                    raise EnglishError("Declare the assignment target first.", span, question=True)
                if not symbol["mutable"]:
                    raise EnglishError(f"'{symbol['name']}' is immutable; declare it mutable to change it.", span)
                value = self.expr(match[2], span["end"] - len(match[2]))
                if value["type"] != symbol["type"]:
                    raise EnglishError("Assignment cannot change a variable's type.", span)
                body.append(node("Assign", span, slot=symbol["id"], value=value))
                continue
            match = re.fullmatch(r"append (.+?) to (.+)", text, re.I)
            if match:
                # Articles and it/them follow the same name rules as assignment.
                symbol = self.resolve_reference(match[2], span)
                if not symbol:
                    raise EnglishError("Declare the list before appending to it.", span, question=True)
                if not symbol["type"].startswith("list["):
                    raise EnglishError("Append requires a list.", span)
                if not symbol["mutable"]:
                    raise EnglishError(f"'{symbol['name']}' is immutable; declare it mutable to append to it.", span)
                item = self.expr(match[1], span["start"] + match.start(1))
                element = symbol["type"][5:-1]
                if item["type"] != element:
                    raise EnglishError(f"Append requires {element}, not {item['type']}.", span)
                body.append(node("Append", span, slot=symbol["id"], value=item))
                continue
            match = re.fullmatch(r"what is (.+)", text, re.I)
            if match:
                body.append(node("Show", span, value=self.expr(match[1], span["start"] + match.start(1))))
                continue
            match = re.fullmatch(rf"{OUTPUT_PATTERN} (?:me )?(.+)|(?:compute|calculate) ((?:the )?(?:sum|total|aggregate|difference|product|quotient|remainder) of .+)", text, re.I)
            if match:
                group = 1 if match[1] is not None else 2
                body.append(node("Show", span, value=self.expr(match[group], span["start"] + match.start(group))))
                continue
            match = re.fullmatch(r"if (.+?) then", text, re.I)
            if match:
                condition = self.expr(match[1], span["start"] + match.start(1))
                if condition["type"] != "boolean":
                    raise EnglishError("If requires a boolean condition.", span)
                body.append(self.conditional(condition, span, depth, close=True))
                continue
            match = re.fullmatch(r"for each (.+?) from (.+?) to (.+)", text, re.I)
            if match and not re.search(r"\bin\b", match[1], re.I):
                start = self.expr(match[2], span["start"] + match.start(2))
                limit = self.expr(match[3], span["start"] + match.start(3))
                if start["type"] != "integer" or limit["type"] != "integer":
                    raise EnglishError("Counted loops require integer bounds.", span)
                # Declared outside the while: each iteration clears only scoped slots.
                counter = self.declare(match[1], "integer", True, span)
                body.append(node("Declare", span, slot=counter["id"], value=start))
                condition = node("Binary", span, operator="less_equal", type="boolean",
                                 left=node("Name", span, slot=counter["id"], name=counter["name"], type="integer"),
                                 right=limit)
                self.scopes.append({})
                loop = self.block("loop", depth + 1)
                slots = [symbol["id"] for symbol in self.scopes.pop().values()]
                self.finish({"end the loop", "end loop"}, span)
                loop.append(node("Assign", span, slot=counter["id"], value=node(
                    "Binary", span, operator="add", type="integer",
                    left=node("Name", span, slot=counter["id"], name=counter["name"], type="integer"),
                    right=node("Literal", span, value=1, type="integer"))))
                body.append(node("While", span, condition=condition, body=loop, scoped_slots=slots))
                continue
            match = re.fullmatch(r"for each (.+?) in (.+)", text, re.I)
            if match:
                value = self.expr(match[2], span["end"] - len(match[2]))
                if not value["type"].startswith("list["):
                    raise EnglishError("For each requires a list.", span)
                self.scopes.append({})
                item = self.declare(match[1], value["type"][5:-1], False, span)
                loop = self.block("loop", depth+1)
                slots = [s["id"] for s in self.scopes.pop().values()]
                self.finish({"end the loop", "end loop"}, span)
                body.append(node("For", span, value=value, slot=item["id"], body=loop, scoped_slots=slots))
                continue
            match = re.fullmatch(r"repeat (.+) times", text, re.I)
            if match:
                count = self.expr(match[1], span["start"] + match.start(1))
                if count["type"] != "integer":
                    raise EnglishError("Repeat requires an integer count.", span)
                # Count is fixed at entry. The hidden counter is outside the while scope.
                limit = self.hidden_integer("limit")
                counter = self.hidden_integer("repeat")
                body.append(node("Declare", span, slot=limit["id"], value=count))
                body.append(node("Declare", span, slot=counter["id"], value=node("Literal", span, value=0, type="integer")))
                condition = node("Binary", span, operator="less", type="boolean",
                                 left=node("Name", span, slot=counter["id"], name=counter["name"], type="integer"),
                                 right=node("Name", span, slot=limit["id"], name=limit["name"], type="integer"))
                self.scopes.append({})
                loop = self.block("loop", depth + 1)
                slots = [symbol["id"] for symbol in self.scopes.pop().values()]
                self.finish({"end the loop", "end loop"}, span)
                loop.append(node("Assign", span, slot=counter["id"], value=node(
                    "Binary", span, operator="add", type="integer",
                    left=node("Name", span, slot=counter["id"], name=counter["name"], type="integer"),
                    right=node("Literal", span, value=1, type="integer"))))
                body.append(node("While", span, condition=condition, body=loop, scoped_slots=slots))
                continue
            match = re.fullmatch(r"while (.+?)(?: do)?", text, re.I)
            if match:
                condition = self.expr(match[1], span["start"] + 6)
                if condition["type"] != "boolean":
                    raise EnglishError("While requires a boolean condition.", span)
                self.scopes.append({})
                loop = self.block("loop", depth+1)
                slots = [s["id"] for s in self.scopes.pop().values()]
                self.finish({"end the loop", "end loop"}, span)
                body.append(node("While", span, condition=condition, body=loop, scoped_slots=slots))
                continue
            kind_match = KIND.fullmatch(text)
            if kind_match:
                if depth or self.return_type:
                    raise EnglishError("Kinds must be declared at program scope.", span)
                self.ready.add(kind_match.group(1).lower())
                continue
            make = re.fullmatch(r"make a new (.+)", text, re.I)
            if make:
                rest = make.group(1)
                kind = None
                for name in sorted(self.classes, key=len, reverse=True):
                    prefix = name + " called "
                    if rest.lower().startswith(prefix):
                        kind = self.require_kind(name, span)
                        rest = rest[len(prefix):]
                        break
                if kind is None:
                    guessed = rest.split(" called ", 1)[0].lower()
                    raise EnglishError(f"There is no kind named '{guessed}'. Define it first: A {guessed} has ...", span)
                parts = re.fullmatch(r"(.+?) with (.+)", rest, re.I)
                if not parts:
                    raise EnglishError("Name the new value and give every field, for example 'Make a new point called p with x 3 and y 4.'", span, question=True)
                given, order, missing = Expressions(parts.group(2), span["end"] - len(parts.group(2)), self).initializers(kind)
                if missing:
                    raise EnglishError(missing_fields_message(kind["name"], missing), span, question=True)
                symbol = self.declare(parts.group(1), f"object[{kind['name']}]", True, span)
                kind["used"] = True
                value = node("New", span, layout=kind["id"], type=f"object[{kind['name']}]",
                             values=[given[field["name"]] for field in kind["fields"]], order=order,
                             field_types=[field["type"] for field in kind["fields"]])
                body.append(node("Declare", span, slot=symbol["id"], value=value))
                continue
            raise EnglishError("This clause is not implemented by the general computation grammar.", span)
        if end is not None:
            raise EnglishError(f"Close the {end} explicitly before continuing.", {"start": len(self.source), "end": len(self.source)}, question=True)
        return body

    def finish(self, endings, span):
        if self.at >= len(self.clauses) or self.clauses[self.at][0].lower() not in endings:
            raise EnglishError("Use the matching explicit block ending.", span, question=True)
        self.at += 1


def parse_general(source, bindings=None):
    tokens = [{"text": m.group(), "span": {"start": m.start(), "end": m.end()}} for m in TOKEN.finditer(source) if m.group() != "\ufeff"]
    tree = node("Program", {"start": 0, "end": len(source)}, body=[])
    errors, questions, symbols = [], [], []
    try:
        if bindings:
            raise EnglishError("External bindings are not implemented in the pure computation profile; declare values in English.", tree["span"])
        parser = Parser(source)
        tree["body"] = parser.block()
        tree["functions"] = parser.function_nodes
        tree["layouts"] = parser.published_layouts()
        symbols = parser.symbols
        if not tree["body"] and not tree["functions"]:
            raise EnglishError("Supply a computation to compile.", tree["span"], question=True)
    except EnglishError as error:
        if error.question:
            questions.append({"id": f"general-{error.span['start']}", "question": error.message, "span": error.span, "choices": []})
        else:
            errors.append({"level": "error", "code": error.code or "SMBG100", "message": error.message, "span": error.span})
    except UnicodeError:
        errors.append({"level": "error", "code": "SMBG102", "message": "Text must contain valid Unicode scalar values.", "span": tree["span"]})
    except RecursionError:
        errors.append({"level": "error", "code": "SMBG101", "message": "Expression nesting exceeds the supported limit.", "span": tree["span"]})
    return tokens, tree, {"locals": symbols}, errors, questions
