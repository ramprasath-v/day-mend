import { FamilyProfile } from '../core/family.service';

export const familyFixture: FamilyProfile = {
  version: 1,
  caregivers: [{
    caregiver_id: 'helper', name: 'Family helper', relationship: 'Family',
    availability: [{ start: '2026-08-27T16:00:00Z', end: '2026-08-27T19:15:00Z' }],
    can_transport_child: true, is_trusted: true, location_id: 'helper_home',
  }],
  required_care_schedule: { start: '2026-08-27T15:00:00Z', end: '2026-08-27T23:00:00Z' },
  locations: [{ location_id: 'family_home', location_label: 'Family home' }, { location_id: 'helper_home', location_label: 'Helper home' }],
  preferences: { prefer_trusted_caregivers: false, prefer_in_home_care: false, prefer_fewer_handoffs: true, protect_critical_meetings: false },
  policy: { automatic_spend_limit: '30.00', currency: 'USD', require_approval_for_unfamiliar_paid_caregiver: true, allow_external_backup_providers: true, allow_provider_transport: true },
  notification_mode: 'meaningful_changes',
};
