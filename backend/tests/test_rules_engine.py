"""
Unit Tests for Rules Engine
---------------------------
Tests loading active rules, single-rule lookups, keyword-based relevance retrieval,
graceful handling of empty matches, and strict exclusion of inactive rules.
"""

import json
import pytest
from pathlib import Path
from backend.models.finding import SeverityEnum
from backend.services.rules_engine import (
    RulesEngine,
    RulesFileNotFoundError,
    RulesEngineError,
)


@pytest.fixture
def rules_engine():
    """Returns a RulesEngine instance initialized with the default mock_rules.json."""
    return RulesEngine()


# ==============================================================================
# Rules Loading & Lookup Tests
# ==============================================================================

def test_load_all_and_active_rules(rules_engine: RulesEngine):
    """Verify that rules are loaded from mock_rules.json and active rules are filtered."""
    all_rules = rules_engine.get_all_rules()
    active_rules = rules_engine.get_active_rules()

    assert len(all_rules) >= 8
    assert len(active_rules) >= 8
    for r in active_rules:
        assert r.active is True
        assert r.rule_id
        assert r.name
        assert r.description
        assert isinstance(r.severity_default, SeverityEnum)


def test_get_rule_by_id(rules_engine: RulesEngine):
    """Verify retrieving a specific rule by its ID."""
    rule = rules_engine.get_rule("FINRA-2111")
    assert rule is not None
    assert rule.rule_id == "FINRA-2111"
    assert "Suitability" in rule.name
    assert rule.active is True


def test_get_nonexistent_rule(rules_engine: RulesEngine):
    """Verify looking up a non-existent rule returns None."""
    rule = rules_engine.get_rule("DOES-NOT-EXIST")
    assert rule is None
    assert not rules_engine.is_active_rule("DOES-NOT-EXIST")


# ==============================================================================
# Keyword Matching & Retrieval Tests
# ==============================================================================

def test_retrieve_rules_for_promissory_claims(rules_engine: RulesEngine):
    """Section containing promissory words should match FINRA-2210."""
    section = "We offer guaranteed returns of 18% with zero risk to principal."
    matched = rules_engine.retrieve_relevant_rules(section)

    assert len(matched) > 0
    matched_ids = [r.rule_id for r in matched]
    assert "FINRA-2210" in matched_ids


def test_retrieve_rules_for_hidden_fees(rules_engine: RulesEngine):
    """Section mentioning hidden unilateral fees should match CFPB-UDAAP."""
    section = "A hidden fee of $50 will be charged unilaterally to customer accounts."
    matched = rules_engine.retrieve_relevant_rules(section)

    assert len(matched) > 0
    matched_ids = [r.rule_id for r in matched]
    assert "CFPB-UDAAP" in matched_ids


def test_retrieve_rules_for_unsuitable_recommendation(rules_engine: RulesEngine):
    """Section recommending speculative strategies should match FINRA-2111."""
    section = "The broker recommended a speculative derivatives strategy without evaluating suitability."
    matched = rules_engine.retrieve_relevant_rules(section)

    assert len(matched) > 0
    matched_ids = [r.rule_id for r in matched]
    assert "FINRA-2111" in matched_ids


def test_retrieve_rules_empty_matches_handled_gracefully(rules_engine: RulesEngine):
    """Text without any compliance keywords returns an empty list gracefully."""
    unrelated_text = "The committee met on Tuesday at noon to discuss ordering catering for the office party."
    matched = rules_engine.retrieve_relevant_rules(unrelated_text, fallback_to_all=False)
    assert matched == []


def test_retrieve_rules_fallback_to_all(rules_engine: RulesEngine):
    """When fallback_to_all is True, unrelated text returns baseline active rules."""
    unrelated_text = "Standard internal memo without compliance issues."
    matched = rules_engine.retrieve_relevant_rules(unrelated_text, max_rules=3, fallback_to_all=True)
    assert len(matched) == 3


def test_retrieve_rules_ignores_inactive_rules(tmp_path: Path):
    """Ensure inactive rules are strictly ignored even if their keywords match."""
    custom_rules = [
        {
            "rule_id": "INACTIVE-RULE",
            "name": "Old Expired Rule",
            "category": "Legacy",
            "description": "This rule is no longer in effect.",
            "keywords": ["secret", "guarantee"],
            "severity_default": "LOW",
            "active": False  # Inactive
        },
        {
            "rule_id": "ACTIVE-RULE",
            "name": "Current Enforced Rule",
            "category": "Current",
            "description": "Active rule.",
            "keywords": ["guarantee"],
            "severity_default": "HIGH",
            "active": True  # Active
        }
    ]
    file_path = tmp_path / "custom_rules.json"
    file_path.write_text(json.dumps(custom_rules), encoding="utf-8")

    engine = RulesEngine(rules_path=file_path)
    matched = engine.retrieve_relevant_rules("We guarantee everything.")

    matched_ids = [r.rule_id for r in matched]
    assert "ACTIVE-RULE" in matched_ids
    assert "INACTIVE-RULE" not in matched_ids


def test_missing_rules_file(tmp_path: Path):
    """Ensure RulesFileNotFoundError is raised for missing files."""
    missing = tmp_path / "non_existent_rules.json"
    with pytest.raises(RulesFileNotFoundError):
        RulesEngine(rules_path=missing)

