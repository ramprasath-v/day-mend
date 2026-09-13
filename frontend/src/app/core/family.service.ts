import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { environment } from '../../environments/environment';
import { CoverageWindow } from './recovery.models';

export type NotificationMode = 'decisions_only' | 'meaningful_changes' | 'completion_only';
export interface FamilyCaregiver {
  caregiver_id: string; name: string; relationship: string; availability: CoverageWindow[];
  can_transport_child: boolean; location_id: string; is_trusted: boolean;
}
export interface FamilyPolicy {
  automatic_spend_limit: string;
  currency: string;
  require_approval_for_unfamiliar_paid_caregiver: boolean;
  allow_external_backup_providers: boolean;
  allow_provider_transport: boolean;
}
export interface FamilyProfile {
  version: number;
  caregivers: FamilyCaregiver[];
  required_care_schedule: CoverageWindow;
  preferences: {
    prefer_trusted_caregivers: boolean; prefer_in_home_care: boolean;
    prefer_fewer_handoffs: boolean; protect_critical_meetings: boolean;
  };
  policy: FamilyPolicy;
  notification_mode: NotificationMode;
  locations: { location_id: string; location_label: string }[];
}

@Injectable({ providedIn: 'root' })
export class FamilyService {
  private readonly http = inject(HttpClient);
  private readonly url = environment.apiBaseUrl + '/family';
  get() { return this.http.get<FamilyProfile>(this.url); }
  saveFamily(profile: FamilyProfile) {
    return this.http.put<FamilyProfile>(this.url, {
      expected_version: profile.version,
      required_care_schedule: profile.required_care_schedule,
      caregivers: profile.caregivers.map(caregiver => ({
        caregiver_id: caregiver.caregiver_id, name: caregiver.name, relationship: caregiver.relationship,
        availability: caregiver.availability, can_transport_child: caregiver.can_transport_child,
        location_id: caregiver.location_id, is_trusted: caregiver.is_trusted,
      })),
    });
  }
  savePreferences(profile: FamilyProfile) {
    const preferences = profile.preferences;
    return this.http.put<FamilyProfile>(this.url + '/preferences', {
      expected_version: profile.version,
      prefer_trusted_caregivers: preferences.prefer_trusted_caregivers,
      prefer_in_home_care: preferences.prefer_in_home_care,
      minimize_handoffs: preferences.prefer_fewer_handoffs,
      protect_critical_meetings: preferences.protect_critical_meetings,
    });
  }
  savePolicy(profile: FamilyProfile) {
    return this.http.put<FamilyProfile>(this.url + '/policy', {
      expected_version: profile.version,
      automatic_spend_limit: profile.policy.automatic_spend_limit,
      require_approval_for_unfamiliar_provider: profile.policy.require_approval_for_unfamiliar_paid_caregiver,
      allow_external_backup_providers: profile.policy.allow_external_backup_providers,
      allow_provider_transport: profile.policy.allow_provider_transport,
      notification_mode: profile.notification_mode,
    });
  }
}

export function familyError(error: HttpErrorResponse): string {
  if (error.status === 409) return 'These settings changed elsewhere. Reload before saving again.';
  if (error.status === 422) {
    const detail = error.error?.detail;
    return typeof detail === 'string' ? detail : 'Check the entered values and availability windows.';
  }
  return 'Family settings could not be saved or loaded. Your edits have not been confirmed.';
}

export function localDateTime(value: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '';
  const pad = (number: number) => String(number).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
export function toInstant(value: string): string {
  const date = new Date(value);
  return value && Number.isFinite(date.getTime()) && localDateTime(date.toISOString()) === value
    ? date.toISOString() : '';
}
export function validWindow(window: CoverageWindow): boolean {
  return Number.isFinite(Date.parse(window.start)) && Number.isFinite(Date.parse(window.end))
    && Date.parse(window.start) < Date.parse(window.end);
}
