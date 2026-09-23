"""Compositional, source-linked English for the pure computation profile.

No bytecode, runtime, Core or IR imports. Every clause must be consumed.
"""
from __future__ import annotations

import json
import re

GRAMMAR_VERSION = "general-english-0.4"
CATALOG_VERSION = "pure-computation-0.1"
TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|\d+|[A-Za-z_][A-Za-z_0-9]*|[^\s]')
TYPES = {"integer", "boolean", "text"}
RESERVED = {"it", "them", "true", "false", "and", "or", "not", "the", "a", "an", "if", "then", "otherwise", "end", "let", "set", "show", "for", "each", "while", "be", "to", "in", "of"}
FUNCTION = re.compile(r"define (?:a )?function (.+?)(?: with (.+?))? returning (integer|boolean|text|list of integers|list of booleans|list of text)", re.I)


def type_name(value):
    return {"list of integers": "list[integer]", "list of booleans": "list[boolean]", "list of text": "list[text]"}.get(value.lower(), value.lower())


def returns(body):
    return bool(body) and (body[-1]["kind"] == "Return" or body[-1]["kind"] == "If" and returns(body[-1]["yes"]) and returns(body[-1]["no"]))


class EnglishError(Exception):
    def __init__(self, message, span, *, question=False):
        self.message, self.span, self.question = message, span, question


def node(kind, span, **fields):
    return {"kind": kind, "span": dict(span), **fields}


def clauses(source):
    """Sentence/block delimiters outside quoted data, retaining original offsets."""
    # Program wrappers may enclose the whole document or separate paragraphs.
    # Mask delimiters, never trim/rebuild prose: spans index the original source.
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
            link = re.match(r'(?:and\s+then|and|then)\s+(?=(?:please\s+)?(?:show|print|display|let|set|change|start|add|subtract|multiply|divide)\b)', tail, re.I)
            if link:
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
        elif char in ".;:\n":
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
        self.tokens = [(m.group(), offset + m.start(), offset + m.end()) for m in TOKEN.finditer(text)]
        self.at, self.owner = 0, owner
        self.span = {"start": offset, "end": offset + len(text)}

    def take(self, *words):
        if [t[0].lower() for t in self.tokens[self.at:self.at+len(words)]] == list(words):
            self.at += len(words)
            return True
        return False

    def fail(self, message, question=False):
        span = {"start": self.tokens[self.at][1], "end": self.tokens[self.at][2]} if self.at < len(self.tokens) else self.span
        raise EnglishError(message, span, question=question)

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
            (("times",), "multiply", 5),
            (("and",), "and", 2), (("or",), "or", 1),
        ]
        while True:
            found = False
            for words, operator, priority in operators:
                if priority >= minimum and self.take(*words):
                    right = self.expression(priority + 1)
                    if priority >= 4:
                        if infix_arithmetic or (right["kind"] == "Binary" and right["operator"] in {"add", "subtract", "multiply", "divide", "modulo"} and not right.get("explicit_group")):
                            self.fail("State arithmetic grouping explicitly using parentheses or 'the sum/product of'.", question=True)
                        infix_arithmetic = True
                    left = self.binary(operator, left, right)
                    found = True
                    break
            if not found:
                return left

    def binary(self, operator, left, right):
        ltype, rtype = left["type"], right["type"]
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
        self.take("the")
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
        for word, operator, separator in (("sum", "add", "and"), ("difference", "subtract", "and"), ("product", "multiply", "and"), ("quotient", "divide", "and"), ("remainder", "modulo", "and")):
            if self.take(word, "of"):
                left = self.expression(4)
                if not self.take(separator):
                    self.fail(f"State both operands: {word} of one value and another.", question=True)
                right = self.expression(4)
                value = self.binary(operator, left, right)
                value["explicit_group"] = True
                return value
        if self.take("length", "of") or self.take("number", "of", "items", "in"):
            value = self.atom()
            if not value["type"].startswith("list["):
                self.fail("Length requires a list.")
            return node("Length", self.range(begin), value=value, type="integer")
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
                elif not self.take("and"):
                    break
            return node("List", self.range(begin), values=values, type=f"list[{element}]")
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
        for name, symbol in sorted(self.owner.visible().items(), key=lambda pair: -len(pair[0])):
            words = name.split()
            if self.take(*words):
                return node("Name", self.range(begin), slot=symbol["id"], name=name, type=symbol["type"])
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

    def element_type(self):
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
        # Collect signatures before resolving any function call (including recursion).
        for text, span in self.clauses:
            match = FUNCTION.fullmatch(re.sub(r"^please\s+", "", text, flags=re.I))
            if not match:
                continue
            name, params, result_type = match.groups()
            name = name.lower()
            if name in self.functions or not re.fullmatch(r"[a-z_][a-z_0-9]*(?: [a-z_][a-z_0-9]*)*", name) or any(w in RESERVED for w in name.split()):
                raise EnglishError("Function names must be distinct explicit names without reserved words.", span)
            parameters = []
            for definition in re.split(r"\s+and\s+", params, flags=re.I) if params else []:
                param = re.fullmatch(r"(integer|boolean|text|list of integers|list of booleans|list of text) parameter (.+)", definition, re.I)
                if not param:
                    raise EnglishError("Declare each typed parameter, for example 'integer parameter amount'.", span, question=True)
                parameters.append({"name": param[2].lower(), "type": type_name(param[1])})
            self.functions[name] = {"id": len(self.functions), "name": name, "parameters": parameters, "return_type": type_name(result_type)}

    def visible(self):
        return {key: value for scope in self.scopes for key, value in scope.items()}

    def declare(self, name, kind, mutable, span):
        name = name.lower()
        if not re.fullmatch(r"[a-z_][a-z_0-9]*(?: [a-z_][a-z_0-9]*)*", name) or any(w in RESERVED for w in name.split()):
            raise EnglishError("Use an explicit name without reserved grammar words.", span)
        if name in self.visible():
            raise EnglishError(f"'{name}' is already declared; shadowing is not permitted.", span)
        symbol = {"id": len(self.symbols), "name": name, "type": kind, "mutable": mutable}
        self.symbols.append(symbol)
        self.scopes[-1][name] = symbol
        return symbol

    def expr(self, text, offset):
        return Expressions(text, offset, self).parse()

    def block(self, end=None, depth=0):
        if depth > 64:
            raise EnglishError("Block nesting exceeds 64 levels.", {"start": 0, "end": len(self.source)})
        body = []
        while self.at < len(self.clauses):
            text, span = self.clauses[self.at]
            lower = text.lower()
            if lower in {"otherwise", "else", "end the condition", "end if", "end the loop", "end loop", "end the function", "end function"}:
                if end is None:
                    raise EnglishError("This block ending has no matching opening.", span, question=True)
                return body
            if returns(body):
                raise EnglishError("This statement cannot run because the preceding paths return.", span)
            self.at += 1
            polite = re.match(r"(?:please\s+)", text, re.I)
            if polite:
                text = text[polite.end():]
                span = {"start": span["start"] + polite.end(), "end": span["end"]}
            match = re.fullmatch(r"start with (?:(.+?) at )?(.+)", text, re.I)
            if match:
                value = self.expr(match[2], span['start'] + match.start(2))
                symbol = self.declare(match[1] or 'result', value['type'], True, span)
                body.append(node('Declare', span, slot=symbol['id'], value=value))
                continue
            implicit = re.fullmatch(r"(add|subtract) (.+)", text, re.I)
            match = re.fullmatch(r"(add|subtract) (.+?) (to|from) (.+)|(multiply|divide) (.+?) by (.+)", text, re.I)
            if implicit and not match:
                candidates = [s for s in self.visible().values() if s['mutable'] and s['type'] == 'integer']
                if len(candidates) != 1:
                    raise EnglishError('Name the arithmetic target explicitly.', span, question=True)
                symbol = candidates[0]
                right = self.expr(implicit[2], span['start'] + implicit.start(2))
                if right['type'] != 'integer':
                    raise EnglishError('Arithmetic updates require an integer.', span)
                value = node('Binary', span, operator=implicit[1].lower(), left=node('Name', span, slot=symbol['id'], type='integer'), right=right, type='integer')
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
                symbol = self.visible().get(name.lower())
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
                if prefix:
                    mutable = bool(prefix[1])
                    declared_type, rhs = prefix[2].lower(), prefix[3]
                elif re.match(r"(?:a )?mutable\b", rhs, re.I):
                    raise EnglishError("Declare a mutable type and its initial value explicitly.", span, question=True)
                offset = span["end"] - len(rhs)
                value = self.expr(rhs, offset)
                if declared_type and declared_type != value["type"]:
                    raise EnglishError("The initial value does not match the declared type.", span)
                symbol = self.declare(name, value["type"], mutable, span)
                body.append(node("Declare", span, slot=symbol["id"], value=value))
                continue
            match = re.fullmatch(r"(?:set|change) (.+?) to (.+)", text, re.I)
            if match:
                symbol = self.visible().get(match[1].lower())
                if not symbol:
                    raise EnglishError("Declare the assignment target first.", span, question=True)
                if not symbol["mutable"]:
                    raise EnglishError(f"'{symbol['name']}' is immutable; declare it mutable to change it.", span)
                value = self.expr(match[2], span["end"] - len(match[2]))
                if value["type"] != symbol["type"]:
                    raise EnglishError("Assignment cannot change a variable's type.", span)
                body.append(node("Assign", span, slot=symbol["id"], value=value))
                continue
            match = re.fullmatch(r"(?:show|print|display) (?:me )?(.+)", text, re.I)
            if match:
                body.append(node("Show", span, value=self.expr(match[1], span["end"] - len(match[1]))))
                continue
            match = re.fullmatch(r"if (.+?) then", text, re.I)
            if match:
                condition = self.expr(match[1], span["start"] + 3)
                if condition["type"] != "boolean":
                    raise EnglishError("If requires a boolean condition.", span)
                self.scopes.append({})
                yes = self.block("condition", depth+1)
                yes_slots = [s["id"] for s in self.scopes.pop().values()]
                no, no_slots = [], []
                if self.at < len(self.clauses) and self.clauses[self.at][0].lower() in {"otherwise", "else"}:
                    self.at += 1
                    self.scopes.append({})
                    no = self.block("condition", depth+1)
                    no_slots = [s["id"] for s in self.scopes.pop().values()]
                self.finish({"end the condition", "end if"}, span)
                body.append(node("If", span, condition=condition, yes=yes, no=no, yes_slots=yes_slots, no_slots=no_slots))
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
            raise EnglishError("This clause is not implemented by the general computation grammar.", span)
        if end is not None:
            raise EnglishError(f"Close the {end} explicitly before continuing.", {"start": len(self.source), "end": len(self.source)}, question=True)
        return body

    def finish(self, endings, span):
        if self.at >= len(self.clauses) or self.clauses[self.at][0].lower() not in endings:
            raise EnglishError("Use the matching explicit block ending.", span, question=True)
        self.at += 1


def parse_general(source, bindings=None):
    tokens = [{"text": m.group(), "span": {"start": m.start(), "end": m.end()}} for m in TOKEN.finditer(source)]
    tree = node("Program", {"start": 0, "end": len(source)}, body=[])
    errors, questions, symbols = [], [], []
    try:
        if bindings:
            raise EnglishError("External bindings are not implemented in the pure computation profile; declare values in English.", tree["span"])
        parser = Parser(source)
        tree["body"] = parser.block()
        tree["functions"] = parser.function_nodes
        symbols = parser.symbols
        if not tree["body"] and not tree["functions"]:
            raise EnglishError("Supply a computation to compile.", tree["span"], question=True)
    except EnglishError as error:
        if error.question:
            questions.append({"id": f"general-{error.span['start']}", "question": error.message, "span": error.span, "choices": []})
        else:
            errors.append({"level": "error", "code": "SMBG100", "message": error.message, "span": error.span})
    except UnicodeError:
        errors.append({"level": "error", "code": "SMBG102", "message": "Text must contain valid Unicode scalar values.", "span": tree["span"]})
    except RecursionError:
        errors.append({"level": "error", "code": "SMBG101", "message": "Expression nesting exceeds the supported limit.", "span": tree["span"]})
    return tokens, tree, {"locals": symbols}, errors, questions
