"""Typed vision grammar. Parsing does not load the engine."""
import re

from .vision import OPERATIONS, validate_arguments


def operation_node(op, arguments, span):
    from .general_english import EnglishError, node

    signature = OPERATIONS.get(op)
    if not signature or [item["type"] for item in arguments] != signature[0]:
        raise EnglishError("Invalid vision operation or operand types.", span)

    def constant(item):
        if item["kind"] == "Literal":
            return True, item["value"]
        return False, None

    constants = [constant(item) for item in arguments]
    if all(known for known, _value in constants):
        try:
            validate_arguments(op, [value for _known, value in constants])
        except ValueError as error:
            raise EnglishError(str(error), span) from error
    return node("VisionQuery", span, operation=op, arguments=arguments, type=signature[1])


def _mask(text):
    return re.sub(r'"(?:\\.|[^"\\])*"', lambda match: "x" * len(match[0]), text)


def parse_vision_clause(parser, text, span):
    masked = _mask(text)
    rules = (
        (r"look at (.+) and tell me what is in it", "describe", (1,)),
        (r"look at (.+) and tell me (.+)", "ask", (1, 2)),
        (r"read the text in (.+)", "read_text", (1,)),
        (r"does (.+) show (.+)", "yes_no", (1, 2)),
        (r"count the (.+) in (.+)", "count", (1, 2)),
    )
    for pattern, op, groups in rules:
        match = re.fullmatch(pattern, masked, re.I)
        if not match:
            continue
        arguments = [parser.expr(text[match.start(index):match.end(index)], span["start"] + match.start(index)) for index in groups]
        return operation_node(op, arguments, span)
    return None


def _top_level(expr, word):
    depth = 0
    for index in range(expr.at, len(expr.tokens)):
        token = expr.tokens[index][0]
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
        elif depth == 0 and token.lower() == word:
            return True
    return False


def parse_vision_expression(expr, begin):
    if expr.at >= len(expr.tokens):
        return None
    word = expr.tokens[expr.at][0].lower()
    if word == "look" and expr.take("look", "at"):
        image = expr.expression(3)
        if expr.take("and", "tell", "me", "what", "is", "in", "it"):
            return operation_node("describe", [image], expr.range(begin))
        if expr.take("and", "tell", "me"):
            return operation_node("ask", [image, expr.expression(3)], expr.range(begin))
        expr.fail("Say what to ask after look at.", question=True)
    if word == "read" and expr.take("read", "the", "text", "in"):
        return operation_node("read_text", [expr.expression(3)], expr.range(begin))
    if word == "does" and _top_level(expr, "show"):
        expr.at += 1
        image = expr.expression(3)
        if not expr.take("show"):
            expr.fail("Say what the picture should show.", question=True)
        return operation_node("yes_no", [image, expr.expression(3)], expr.range(begin))
    if word == "count" and expr.at + 1 < len(expr.tokens) and expr.tokens[expr.at + 1][0].lower() == "the" and _top_level(expr, "in"):
        expr.at += 2
        thing = expr.expression(3)
        if not expr.take("in"):
            expr.fail("Name the picture after in.", question=True)
        return operation_node("count", [thing, expr.expression(3)], expr.range(begin))
    return None
