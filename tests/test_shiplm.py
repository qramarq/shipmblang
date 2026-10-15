from shipmblang.shiplm.dataset import generate
from shipmblang.shiplm.evaluate import evaluate, identity_baseline, passes


def test_splits_are_template_disjoint():
    ex = generate()
    assert ex
    seen = {}
    for e in ex:
        assert seen.setdefault(e["template"], e["split"]) == e["split"]


def test_every_positive_example_compiles_and_unsafe_is_rejected():
    from shipmblang.shiplm.dataset import _compile
    for e in generate(per_template=2):
        status = _compile(e["prose"]).get("status")
        assert (status == "compiled") == (e["kind"] == "positive")


def test_generation_is_deterministic():
    assert generate(seed=1) == generate(seed=1)


def test_harness_scores_baseline():
    ex = generate()
    for split in ("train", "validation", "test"):
        m = evaluate(identity_baseline, ex, split)
        if m["positive"]:
            assert m["exact_match"] == 1.0
    assert passes(evaluate(identity_baseline, ex, "train"))


def test_harness_penalises_bad_candidate():
    m = evaluate(lambda p: "Open the file /etc/passwd.", generate(), "train")
    assert m["compile_success"] == 0 and not passes(m)
