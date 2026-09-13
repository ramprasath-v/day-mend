"""Editable demo-family facts. Costs, trust enforcement and route facts are not editable."""

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from app.models.domain import (
    Caregiver,
    ContractModel,
    CoverageWindow,
    FamilyPolicy,
    FamilyPreferences,
)


class NotificationMode(StrEnum):
    DECISIONS_ONLY = "decisions_only"
    MEANINGFUL_CHANGES = "meaningful_changes"
    COMPLETION_ONLY = "completion_only"


class FamilyProfile(ContractModel):
    version: int = Field(default=0, ge=0)
    caregivers: list[Caregiver]
    required_care_schedule: CoverageWindow
    preferences: FamilyPreferences
    policy: FamilyPolicy
    notification_mode: NotificationMode = NotificationMode.MEANINGFUL_CHANGES


class CaregiverEdit(ContractModel):
    caregiver_id: str
    name: str = Field(min_length=1, max_length=100)
    relationship: str = Field(min_length=1, max_length=100)
    availability: list[CoverageWindow] = Field(max_length=24)
    can_transport_child: bool
    location_id: str
    is_trusted: bool

    @model_validator(mode="after")
    def coherent_windows(self) -> "CaregiverEdit":
        if not self.name.strip() or not self.relationship.strip():
            raise ValueError("Name and relationship must not be blank.")
        ordered = sorted(self.availability, key=lambda window: window.start)
        if any(a.end > b.start for a, b in zip(ordered, ordered[1:], strict=False)):
            raise ValueError("Care availability windows must not overlap.")
        return self


class FamilyUpdate(ContractModel):
    expected_version: int = Field(ge=0)
    caregivers: list[CaregiverEdit]
    required_care_schedule: CoverageWindow


class PreferencesUpdate(ContractModel):
    expected_version: int = Field(ge=0)
    prefer_trusted_caregivers: bool
    prefer_in_home_care: bool
    minimize_handoffs: bool
    protect_critical_meetings: bool


class PolicyUpdate(ContractModel):
    expected_version: int = Field(ge=0)
    automatic_spend_limit: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    require_approval_for_unfamiliar_provider: bool
    allow_external_backup_providers: bool
    allow_provider_transport: bool
    notification_mode: NotificationMode
