"""Score only the bundled synthetic corpus. Default execution is offline."""
import argparse
import asyncio
import json
import statistics
import sys
import time
from unittest.mock import patch

from backend.config import settings
from backend.models.document import DocumentChunk
from backend.services.llm_orchestrator import (
    GeminiLLMProvider, LLMAuthenticationError, LLMError, LLMModelNotFoundError,
    LLMOrchestrator, LLMPermissionDeniedError, MockLLMProvider,
)
from backend.services.rules_engine import RulesEngine
from backend.services.validator import Validator
from evaluation.benchmark import CASES, metrics


async def evaluate(live=False):
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    if len(cases) != 20:
        raise ValueError("Approved evaluation requires 20 targets.")
    if live:
        if (settings.LLM_PROVIDER, settings.LLM_MODEL_ID) != ("gemini", "gemini-3.5-flash"):
            raise ValueError("Configured provider or model differs from the evaluation plan.")
        from google.genai import types
        provider = GeminiLLMProvider(settings.LLM_MODEL_ID, request_options={
            "max_output_tokens": 1024,
            "http_options": types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
        })
    else:
        provider = MockLLMProvider()
    model = LLMOrchestrator(provider=provider, max_retries=2)
    engine = RulesEngine()
    validator = Validator(rules_engine=engine)
    sections = [0, 0, 0]
    pairs = [0, 0, 0]
    tn = candidates = exact = invalid = rejected = 0
    latency = []
    successes = 0
    failures = []
    generate = provider.generate_response

    async def measured(**kwargs):
        nonlocal successes
        if len(latency) >= 40:
            raise RuntimeError("Approved request budget exhausted.")
        if live:
            print(f"Provider attempt {len(latency)+1}/40", file=sys.stderr, flush=True)
        start = time.perf_counter()
        try:
            value = await generate(**kwargs)
            successes += 1
            return value
        finally:
            latency.append(time.perf_counter() - start)

    with patch.object(provider, "generate_response", measured):
        for i, case in enumerate(cases):
            target = case["target"]
            prefix = case["before"] + "\n\n" if case["before"] else ""
            suffix = "\n\n" + case["after"] if case["after"] else ""
            radius = settings.INSPECTION_CONTEXT_CHARS
            chunk = DocumentChunk(index=0, text=target, char_start=len(prefix), char_end=len(prefix)+len(target))
            rules, strategy = engine.select_for_inspection(target, settings.RULE_RETRIEVAL_MODE)
            ids = {r.rule_id for r in rules}
            try:
                raw = await model.analyze_section(str(i), chunk, rules, before=prefix[-radius:] if radius else "",
                                                  after=suffix[:radius])
            except LLMError as exc:
                failures.append({"case": case["case"], "error": type(exc).__name__})
                if isinstance(exc, (LLMAuthenticationError, LLMPermissionDeniedError, LLMModelNotFoundError)):
                    break
                continue
            predicted = set()
            for f in raw:
                result = validator.validate_single_finding(f, prefix+target+suffix, str(i), chunk, strategy, ids)
                candidates += 1
                exact += f.passage in target
                if f.rule_id not in ids:
                    invalid += 1
                    rejected += not result.is_valid
                if result.is_valid:
                    predicted.add((f.rule_id, f.passage))
            gold = {(f["rule_id"], f["passage"]) for f in case["expected"]}
            for j, n in enumerate((len(predicted & gold), len(predicted-gold), len(gold-predicted))):
                pairs[j] += n
            for j, positive in enumerate((bool(predicted and gold), bool(predicted and not gold), bool(gold and not predicted))):
                sections[j] += positive
            tn += not predicted and not gold
            if live:
                print(json.dumps(dict(case=case["case"], section_counts=sections, tn=tn,
                                      finding_counts=pairs, attempts=len(latency), responses=successes)),
                      file=sys.stderr, flush=True)
    return dict(provider=settings.LLM_MODEL_ID if live else "mock", section=dict(metrics(*sections), tn=tn),
                finding=metrics(*pairs), scored=sum(sections)+tn, failures=failures,
                candidates=candidates, exact_quotes=exact, invalid_rules=invalid, invalid_rules_rejected=rejected,
                attempts=len(latency), provider_responses=successes, mean_attempt_seconds=statistics.mean(latency))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-live-gemini", action="store_true")
    print(json.dumps(asyncio.run(evaluate(parser.parse_args().approved_live_gemini)), indent=2))
