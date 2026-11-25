"""
Rules Engine Service
--------------------
Loads compliance rules from the mock rules database (JSON) and provides
retrieval mechanisms to match relevant rules against document sections.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
from backend.config import MOCK_RULES_PATH
from backend.models.rule import ComplianceRule


class RulesEngineError(Exception):
    """Base exception for Rules Engine operations."""
    pass


class RulesFileNotFoundError(RulesEngineError):
    """Raised when the rules JSON file cannot be found."""
    pass


class RulesEngine:
    """
    Manages regulatory compliance rules and section-level rule retrieval.
    """

    def __init__(self, rules_path: Optional[Union[str, Path]] = None):
        """
        Initializes the rules database.
        
        Args:
            rules_path: Optional custom path to mock_rules.json.
                        Defaults to the configured MOCK_RULES_PATH.
        """
        self.rules_path = Path(rules_path) if rules_path else MOCK_RULES_PATH
        self._rules: Dict[str, ComplianceRule] = {}
        self.load_rules()

    def load_rules(self) -> None:
        """
        Loads and parses rules from the JSON file into Pydantic models.
        """
        if not self.rules_path.exists():
            raise RulesFileNotFoundError(f"Rules file not found at: {self.rules_path}")

        try:
            raw_content = self.rules_path.read_text(encoding="utf-8")
            data = json.loads(raw_content)
        except json.JSONDecodeError as e:
            raise RulesEngineError(f"Failed to parse rules JSON from {self.rules_path}: {e}")

        self._rules = {}
        for item in data:
            rule = ComplianceRule.model_validate(item)
            self._rules[rule.rule_id] = rule

    def get_rule(self, rule_id: str) -> Optional[ComplianceRule]:
        """
        Retrieves a single rule by its rule_id.
        """
        return self._rules.get(rule_id.strip())

    def get_all_rules(self) -> List[ComplianceRule]:
        """
        Returns all rules in the database (active and inactive).
        """
        return list(self._rules.values())

    def get_active_rules(self) -> List[ComplianceRule]:
        """
        Returns only currently active rules.
        """
        return [rule for rule in self._rules.values() if rule.active]

    def is_active_rule(self, rule_id: str) -> bool:
        """
        Quick boolean check whether a rule_id corresponds to an active rule.
        """
        rule = self.get_rule(rule_id)
        return rule is not None and rule.active

    def retrieve_relevant_rules(
        self,
        text: str,
        max_rules: int = 4,
        fallback_to_all: bool = False
    ) -> List[ComplianceRule]:
        """
        Retrieves the most applicable rules for a given document section using keyword matching.
        
        Algorithm:
        1. Filters only active rules (inactive rules are strictly ignored).
        2. Normalizes section text to lowercase.
        3. Scores each active rule based on the frequency and presence of its keywords.
        4. If matching rules are found, returns the top `max_rules` sorted by relevance score.
        5. Handles empty matches gracefully by returning [] (or all active if fallback_to_all is True).
           
        Args:
            text: Document section text to analyze.
            max_rules: Maximum number of rules to return.
            fallback_to_all: If True and no keywords match, returns up to max_rules active rules.
                             Defaults to False (graceful empty match).
            
        Returns:
            List of relevant ComplianceRule instances containing rule_id, name,
            description, and severity_default.
        """
        if not text or not text.strip():
            return []

        active_rules = self.get_active_rules()
        if not active_rules:
            return []

        text_lower = text.lower()
        scored_rules = []

        for rule in active_rules:
            score = 0
            for kw in rule.keywords:
                kw_lower = kw.lower()
                occurrences = text_lower.count(kw_lower)
                if occurrences > 0:
                    score += occurrences * 2  # Weight keyword matches

            if score > 0:
                scored_rules.append((score, rule))

        if scored_rules:
            # Sort descending by score
            scored_rules.sort(key=lambda x: x[0], reverse=True)
            return [rule for _, rule in scored_rules[:max_rules]]

        # Graceful empty match handling
        if fallback_to_all:
            return active_rules[:max_rules]
        return []

    def select_for_inspection(self, text: str, mode: str) -> Tuple[List[ComplianceRule], str]:
        if mode == "keyword":
            matches = self.retrieve_relevant_rules(text, max_rules=4)
            if matches:
                return matches, "keyword"
            return self.get_active_rules(), "full_fallback"
        if mode != "full":
            raise ValueError("Unknown inspection rule retrieval mode")
        return self.get_active_rules(), "full_catalog"

    def retrieve_relevant_rules_with_strategy(
        self,
        text: str,
        max_rules: int = 4,
        fallback_to_all: bool = True
    ) -> Tuple[List[ComplianceRule], str]:
        """
        Retrieves applicable rules and explicitly records the retrieval strategy:
        'keyword' if matched by keyword score, 'fallback' if bounded active fallback was used,
        or 'none' if no rules apply.
        
        Args:
            text: Document section text.
            max_rules: Maximum rules to return.
            fallback_to_all: Whether to fall back to top active rules if keywords yield 0 matches.
            
        Returns:
            Tuple of (rules_list, strategy_name).
        """
        if not text or not text.strip():
            return [], "none"

        # 1. Primary strategy: Keyword matching
        keyword_rules = self.retrieve_relevant_rules(text, max_rules=max_rules, fallback_to_all=False)
        if keyword_rules:
            return keyword_rules, "keyword"

        # 2. Secondary strategy: Bounded fallback to active compliance rules
        if fallback_to_all:
            fallback_rules = self.retrieve_relevant_rules(text, max_rules=max_rules, fallback_to_all=True)
            if fallback_rules:
                return fallback_rules, "fallback"

        return [], "none"
