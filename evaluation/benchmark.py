"""Offline section-level benchmark. Run from the repository root."""
import asyncio
import json
import math
from pathlib import Path
from statistics import median
import time
import tracemalloc

from backend.config import settings
from backend.services.llm_orchestrator import LLMOrchestrator
from backend.services.rules_engine import RulesEngine

CASES = Path(__file__).with_name("cases.json")


def metrics(tp, fp, fn):
    return dict(tp=tp, fp=fp, fn=fn, precision=round(tp/(tp+fp), 4) if tp+fp else 0,
                recall=round(tp/(tp+fn), 4) if tp+fn else 0,
                f1=round(2*tp/(2*tp+fp+fn), 4) if 2*tp+fp+fn else 0)


async def run():
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    engine = RulesEngine()
    model = LLMOrchestrator(provider_name="mock", model_id="offline", prompt_version="v1.0")
    rt = [0, 0, 0]
    mt = [0, 0, 0]
    tokens = count = 0
    elapsed = []
    tracemalloc.start()
    cpu = time.process_time()
    for case in cases:
        target = case["target"]
        def select():
            return engine.select_for_inspection(target, settings.RULE_RETRIEVAL_MODE)
        for _ in range(50):
            start = time.perf_counter_ns()
            rules, _ = select()
            elapsed.append((time.perf_counter_ns()-start)/1000)
        selected = {r.rule_id for r in rules}
        expected = set(case["relevant"])
        observed = [len(selected & expected),len(selected-expected),len(expected-selected)]
        rt = [a+b for a,b in zip(rt,observed)]
        sys = model.build_system_prompt()
        radius = settings.INSPECTION_CONTEXT_CHARS
        before = (case["before"] + "\n\n")[-radius:] if radius and case["before"] else ""
        after = ("\n\n" + case["after"])[:radius] if case["after"] else ""
        prompt = model.build_user_prompt(target,rules,before,after)
        tokens += math.ceil((len(sys)+len(prompt))/4)
        count += len(rules)
        response = json.loads(await model._provider.generate_response(sys,prompt,1))
        predictions = {(f["rule_id"], f["passage"]) for f in response}
        gold = {(f["rule_id"], f["passage"]) for f in case["expected"]}
        mt = [a+b for a,b in zip(mt,(len(predictions & gold),len(predictions-gold),len(gold-predictions)))]
    cpu_ms = (time.process_time()-cpu)*1000
    peak=tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return dict(cases=len(cases), retrieval=metrics(*rt), mock_candidates=metrics(*mt),
                avg_rules=count/len(cases),input_token_estimate=tokens, cold_target_requests=len(cases),
                retrieval_median_us=round(median(elapsed),2),benchmark_cpu_ms=round(cpu_ms,1),peak_python_bytes=peak)


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()),indent=2))
