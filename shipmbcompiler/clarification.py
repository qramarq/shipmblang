"""Revision-bound English replacements for focused compiler questions."""
import hashlib


def revision(source):
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def apply_answers(source, questions, answers):
    if answers.get("source_revision") != revision(source):
        raise ValueError("Clarification answers belong to a different source revision.")
    supplied = answers.get("answers")
    if not isinstance(supplied, dict) or not supplied:
        raise ValueError("Supply question IDs and English replacement text.")
    by_id = {q["id"]: q for q in questions}
    changes = []
    for question_id, text in supplied.items():
        if question_id not in by_id:
            raise ValueError("The clarification question is unknown or no longer applies.")
        if not isinstance(text, str) or not text.strip() or text.strip().lower() in {"yes", "no"}:
            raise ValueError("Supply the intended English value or clause, not an unbound yes/no answer.")
        span = by_id[question_id]["span"]
        changes.append({"question_id": question_id, "original_span": dict(span), "answer": text.strip()})
    changes.sort(key=lambda change: change["original_span"]["start"])
    end, delta, parts = 0, 0, []
    for change in changes:
        start, stop = change["original_span"]["start"], change["original_span"]["end"]
        if start < end or stop < start or stop > len(source):
            raise ValueError("Clarification source spans overlap or are invalid.")
        parts.extend([source[end:start], change["answer"]])
        change["revised_span"] = {"start": start + delta, "end": start + delta + len(change["answer"])}
        delta += len(change["answer"]) - (stop - start)
        end = stop
    parts.append(source[end:])
    revised = "".join(parts)
    return revised, {"original_revision": revision(source), "revised_revision": revision(revised), "changes": changes}
