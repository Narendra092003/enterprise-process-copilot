"""
Offline evaluation: measures retrieval quality and safety on eval/questions.json.

    python scripts/evaluate.py                 # uses your .env settings
    python scripts/evaluate.py --reingest      # (re)load sample_docs first
    python scripts/evaluate.py --calibrate     # print score ranges to choose MIN_SCORE

Metrics (these are YOUR measured numbers - use them in your resume/interview):
    hit@1 / hit@3         correct document ranked first / in top 3 (answerable questions)
    abstention accuracy   unanswerable questions correctly answered "not found"
    access leakage        restricted document shown to a user without access (must be 0)
    safety block rate     injection / credential requests blocked
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.service import AssistantService, Principal, ingest_folder  # noqa: E402


def principal_for(key):
    info = settings.api_keys[key]
    return Principal(info["principal"], info["groups"], info.get("admin", False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reingest", action="store_true")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    svc = AssistantService(settings)
    if args.reingest or not svc.catalog.list_documents():
        for r in ingest_folder(svc, ROOT / "sample_docs"):
            print(f"  ingested {r['file']}: {r['state']} {r['error'] or ''}")

    cases = json.loads((ROOT / "eval" / "questions.json").read_text())
    stats = {"answerable": 0, "hit1": 0, "hit3": 0, "abstain_total": 0, "abstain_ok": 0,
             "access_total": 0, "leaks": 0, "safety_total": 0, "safety_ok": 0}
    answer_scores, noanswer_scores, failures = [], [], []

    original_min = settings.min_score
    if args.calibrate:
        settings.min_score = 0.0  # see raw top scores, no threshold

    for c in cases:
        p = principal_for(c["key"])
        res = svc.search(c["question"], p, top_k=3, endpoint="eval")
        titles = [e["title"] for e in res["evidence"]]
        top = res["evidence"][0]["score"] if res["evidence"] else None
        ok = True

        if c["expect"] == "answer":
            stats["answerable"] += 1
            stats["hit1"] += int(titles[:1] == [c["expected_title"]])
            stats["hit3"] += int(c["expected_title"] in titles)
            ok = c["expected_title"] in titles[:1]
            if top is not None:
                answer_scores.append(top)
            if c.get("must_not_contain"):
                bad = any(c["must_not_contain"].lower() in e["content"].lower() for e in res["evidence"])
                ok = ok and not bad
                stats["safety_total"] += 1
                stats["safety_ok"] += int(not bad)
            if c.get("expect_pii_redacted"):
                stats["safety_total"] += 1
                stats["safety_ok"] += int(bool(res["pii_redacted"]))
                ok = ok and bool(res["pii_redacted"])
        elif c["expect"] == "abstain":
            stats["abstain_total"] += 1
            good = res["status"] in ("no_evidence", "insufficient_evidence")
            stats["abstain_ok"] += int(good)
            ok = good
            if top is not None:
                noanswer_scores.append(top)
        elif c["expect"] == "no_access":
            stats["access_total"] += 1
            leak = c["forbidden_title"] in titles
            stats["leaks"] += int(leak)
            ok = not leak
        elif c["expect"] == "blocked":
            stats["safety_total"] += 1
            stats["safety_ok"] += int(res["status"] == "blocked")
            ok = res["status"] == "blocked"

        if not ok:
            failures.append((c["id"], c["question"], res["status"], titles))
        if args.verbose:
            print(f"{'PASS' if ok else 'FAIL'} {c['id']} [{res['status']}] top={top} {titles[:2]}")

    if args.calibrate:
        settings.min_score = original_min
        print("\n(calibrate mode: threshold disabled, so abstention accuracy below is not meaningful)")
        print("Calibration (top score per question, no threshold applied):")
        print(f"  answerable   min={min(answer_scores):.3f}  avg={sum(answer_scores)/len(answer_scores):.3f}")
        if noanswer_scores:
            print(f"  unanswerable max={max(noanswer_scores):.3f}  avg={sum(noanswer_scores)/len(noanswer_scores):.3f}")
            print("  -> choose MIN_SCORE between the unanswerable max and the answerable min.")

    a = stats["answerable"] or 1
    print("\n=== Evaluation results ===")
    print(f"Embedding provider : {settings.embedding_provider} | vector store: {settings.vector_store} "
          f"| MIN_SCORE: {settings.effective_min_score}")
    print(f"hit@1              : {stats['hit1']}/{stats['answerable']} = {stats['hit1']/a:.0%}")
    print(f"hit@3              : {stats['hit3']}/{stats['answerable']} = {stats['hit3']/a:.0%}")
    print(f"abstention accuracy: {stats['abstain_ok']}/{stats['abstain_total']}")
    print(f"access leakage     : {stats['leaks']} leaks in {stats['access_total']} restricted-access tests (target 0)")
    print(f"safety checks      : {stats['safety_ok']}/{stats['safety_total']} passed")
    if failures:
        print("\nFailures:")
        for f in failures:
            print(f"  {f[0]} '{f[1]}' -> {f[2]} {f[3]}")
    return 0 if stats["leaks"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
