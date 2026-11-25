"""
Compliance Rule Model
---------------------
Pydantic schema representing a regulatory compliance rule in the rules database.
"""

from typing import List
from pydantic import BaseModel, Field
from backend.models.finding import SeverityEnum


class ComplianceRule(BaseModel):
    """
    Represents an active or historical compliance rule.
    
    Attributes:
        rule_id: Unique code for the regulation (e.g. 'FINRA-2111').
        name: Human-readable name of the regulation.
        category: High-level classification (e.g. 'Customer Protection').
        description: Full legal/compliance description of the rule.
        keywords: Associated terms for keyword matching against document sections.
        severity_default: Default violation severity level.
        active: Whether the rule is currently enforced.
    """
    rule_id: str = Field(min_length=1, description="Unique regulatory rule ID")
    name: str = Field(min_length=1, description="Rule title")
    category: str = Field(default="General", description="Regulatory category")
    description: str = Field(min_length=5, description="Rule description and obligations")
    keywords: List[str] = Field(default_factory=list, description="Keywords for section matching")
    severity_default: SeverityEnum = Field(default=SeverityEnum.MEDIUM, description="Default severity")
    active: bool = Field(default=True, description="Enforcement status")

