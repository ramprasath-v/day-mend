"""Demo family editing and authoritative scenario snapshots; no planning or hidden replans."""

from collections.abc import Callable
from dataclasses import replace
from datetime import date

from app.fixtures import DemoScenario, get_demo_scenario
from app.fixtures.demo_date import DEMO_TIME_ZONE, resolve_demo_care_date
from app.models import CareLocationType
from app.models.family import FamilyProfile, FamilyUpdate, PolicyUpdate, PreferencesUpdate
from app.repositories.family_repository import FamilyRepository, FamilyVersionConflict


class FamilyService:
    def __init__(
        self,
        repository: FamilyRepository,
        scenario_factory: Callable[[date | None], DemoScenario] = get_demo_scenario,
        demo_date_source: Callable[[], date] = resolve_demo_care_date,
    ) -> None:
        self.repository = repository
        self._scenario_factory = scenario_factory
        self._demo_date_source = demo_date_source

    @staticmethod
    def _seed(scenario: DemoScenario) -> FamilyProfile:
        return FamilyProfile(
            caregivers=list(scenario.caregivers),
            required_care_schedule=scenario.required_coverage,
            preferences=scenario.preferences,
            policy=scenario.policy,
        )

    def get(self) -> FamilyProfile:
        profile = self.repository.get()
        if profile is not None:
            return profile
        scenario = self._scenario_factory(self._demo_date_source())
        seed = self._seed(scenario)
        try:
            return self.repository.save(seed, None)
        except FamilyVersionConflict:
            # Another request seeded it first; never overwrite that request's profile.
            profile = self.repository.get()
            if profile is None:
                raise
            return profile

    def reset_demo(self) -> FamilyProfile:
        """Replace only the demo profile with a coherent current-date canonical seed."""

        current = self.repository.get()
        scenario = self._scenario_factory(self._demo_date_source())
        return self.repository.save(
            self._seed(scenario),
            current.version if current is not None else None,
        )

    def locations(self) -> list[dict]:
        scenario = self.scenario(self.get())
        locations = {
            scenario.family_home_location_id: {
                "location_id": scenario.family_home_location_id,
                "location_label": "Family home",
                "care_location_type": CareLocationType.FAMILY_HOME,
                "travel_minutes_from_family_home": 0,
            }
        }
        for caregiver in scenario.caregivers:
            locations[caregiver.location_id] = {
                key: getattr(caregiver, key)
                for key in (
                    "location_id",
                    "location_label",
                    "care_location_type",
                    "travel_minutes_from_family_home",
                )
            }
        return list(locations.values())

    def update(self, edit: FamilyUpdate) -> FamilyProfile:
        profile = self.get()
        existing = {caregiver.caregiver_id: caregiver for caregiver in profile.caregivers}
        ids = [caregiver.caregiver_id for caregiver in edit.caregivers]
        if len(ids) != len(set(ids)) or set(ids) != set(existing):
            raise ValueError(
                "Update existing caregivers only; provide each caregiver exactly once."
            )
        locations = {location["location_id"]: location for location in self.locations()}
        caregivers = []
        for caregiver in edit.caregivers:
            if caregiver.location_id not in locations:
                raise ValueError("Choose a known location with established travel facts.")
            caregivers.append(
                existing[caregiver.caregiver_id].model_copy(
                    update={
                        **caregiver.model_dump(),
                        **locations[caregiver.location_id],
                        "availability": caregiver.availability,
                    },
                    deep=True,
                )
            )
        return self.repository.save(
            profile.model_copy(
                update={
                    "caregivers": caregivers,
                    "required_care_schedule": edit.required_care_schedule,
                }
            ),
            edit.expected_version,
        )

    def update_preferences(self, edit: PreferencesUpdate) -> FamilyProfile:
        profile = self.get()
        preferences = profile.preferences.model_copy(
            update={
                "prefer_trusted_caregivers": edit.prefer_trusted_caregivers,
                "prefer_in_home_care": edit.prefer_in_home_care,
                "prefer_fewer_handoffs": edit.minimize_handoffs,
                "protect_critical_meetings": edit.protect_critical_meetings,
            }
        )
        return self.repository.save(
            profile.model_copy(update={"preferences": preferences}), edit.expected_version
        )

    def update_policy(self, edit: PolicyUpdate) -> FamilyProfile:
        profile = self.get()
        policy = profile.policy.model_copy(
            update={
                "automatic_spend_limit": edit.automatic_spend_limit,
                "require_approval_for_unfamiliar_paid_caregiver": (
                    edit.require_approval_for_unfamiliar_provider
                ),
                "allow_external_backup_providers": edit.allow_external_backup_providers,
                "allow_provider_transport": edit.allow_provider_transport,
            }
        )
        return self.repository.save(
            profile.model_copy(
                update={
                    "policy": policy,
                    "notification_mode": edit.notification_mode,
                }
            ),
            edit.expected_version,
        )

    def scenario(self, profile: FamilyProfile) -> DemoScenario:
        care_date = profile.required_care_schedule.start.astimezone(DEMO_TIME_ZONE).date()
        return replace(
            self._scenario_factory(care_date),
            caregivers=tuple(profile.caregivers),
            required_coverage=profile.required_care_schedule,
            preferences=profile.preferences,
            policy=profile.policy,
        )
