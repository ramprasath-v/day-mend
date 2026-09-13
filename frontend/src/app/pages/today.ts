import { Component, computed, inject, signal } from '@angular/core';
import { RepairZoneComponent } from '../components/repair-zone/repair-zone';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FamilyService, NotificationMode } from '../core/family.service';
import { DatePipe } from '@angular/common';
import { RecoveryStore } from '../core/recovery.store';
import { CoverageSegment, CoverageWindow, RecoveryEvent } from '../core/recovery.models';
import { friendlyPerson } from '../core/recovery-status';
import { ApprovalCardComponent } from '../components/approval-card/approval-card';
import { CoveragePlanComponent } from '../components/coverage-plan/coverage-plan';
import { DemoControlsComponent } from '../components/demo-controls/demo-controls';
import { LiveRecoveryComponent } from '../components/live-recovery/live-recovery';
import { PlanChangeComponent } from '../components/plan-change/plan-change';
import { RecoveryHeroComponent } from '../components/recovery-hero/recovery-hero';
import { WeekCareStripComponent } from '../components/week-care-strip/week-care-strip';

interface RejectedDayEntry {
  kind: 'covered' | 'unresolved';
  start: string;
  end: string;
  segment?: CoverageSegment;
}

@Component({
  selector: 'app-today',
  imports: [DatePipe, ApprovalCardComponent, CoveragePlanComponent, DemoControlsComponent, LiveRecoveryComponent, PlanChangeComponent, RecoveryHeroComponent, RepairZoneComponent, WeekCareStripComponent],
  templateUrl: './today.html',
  styleUrl: './today.css',
})
export class TodayPage {
  readonly store = inject(RecoveryStore);
  readonly friendlyPerson = friendlyPerson;
  readonly rejected = computed(
    () => this.store.currentCase()?.approval_history.at(-1)?.status === 'REJECTED',
  );
  readonly noOptionEvent = computed(() =>
    [...(this.store.currentCase()?.events ?? [])]
      .reverse()
      .find((event) => event.details['outcome_code'] === 'NO_RECOVERY_OPTION') ?? null,
  );
  readonly noOptionSupportingText = computed(() => {
    const value = this.noOptionEvent()?.details['supporting_text'];
    return typeof value === 'string'
      ? value
      : 'Known caregivers cannot cover the remaining gap with the current family settings.';
  });
  readonly noOptionDay = computed(() => {
    const recovery = this.store.currentCase();
    const event = this.noOptionEvent();
    const prior = recovery?.previous_plans.at(-1);
    if (!event || !prior) return null;

    const preservedIds = this.stringList(event, 'preserved_segment_ids');
    const uncovered = this.coverageWindows(event);
    const entries: RejectedDayEntry[] = [
      ...prior.coverage_segments
        .filter((segment) => preservedIds.includes(segment.segment_id))
        .map((segment) => ({
          kind: 'covered' as const,
          start: segment.window.start,
          end: segment.window.end,
          segment,
        })),
      ...uncovered.map((window) => ({
        kind: 'unresolved' as const,
        start: window.start,
        end: window.end,
      })),
    ].sort((left, right) => Date.parse(left.start) - Date.parse(right.start));
    return { entries, unresolved: uncovered };
  });
  readonly rejectedDay = computed(() => {
    const recovery = this.store.currentCase();
    const prior = recovery?.previous_plans.at(-1);
    const proposed = recovery?.active_plan;
    if (!this.rejected() || !prior || !proposed || prior.coverage_segments.length === 0) {
      return null;
    }

    const preserved = prior.coverage_segments
      .filter((segment) =>
        proposed.coverage_segments.some((candidate) =>
          this.segmentsMateriallyMatch(segment, candidate),
        ),
      )
      .sort((left, right) => Date.parse(left.window.start) - Date.parse(right.window.start));
    const coverageStart = prior.coverage_segments.reduce(
      (earliest, segment) =>
        Date.parse(segment.window.start) < Date.parse(earliest)
          ? segment.window.start
          : earliest,
      prior.coverage_segments[0].window.start,
    );
    const coverageEnd = prior.coverage_segments.reduce(
      (latest, segment) =>
        Date.parse(segment.window.end) > Date.parse(latest) ? segment.window.end : latest,
      prior.coverage_segments[0].window.end,
    );
    const entries: RejectedDayEntry[] = [];
    let cursor = coverageStart;
    for (const segment of preserved) {
      if (Date.parse(segment.window.start) > Date.parse(cursor)) {
        entries.push({ kind: 'unresolved', start: cursor, end: segment.window.start });
      }
      entries.push({
        kind: 'covered',
        start: segment.window.start,
        end: segment.window.end,
        segment,
      });
      if (Date.parse(segment.window.end) > Date.parse(cursor)) cursor = segment.window.end;
    }
    if (Date.parse(cursor) < Date.parse(coverageEnd)) {
      entries.push({ kind: 'unresolved', start: cursor, end: coverageEnd });
    }
    return {
      entries,
      unresolved: entries.filter((entry) => entry.kind === 'unresolved'),
    };
  });
  readonly declineConfirmed = computed(() => {
    const events = this.store.progressEvents();
    const accepted = events.reduce((last, e, index) => e.event_type === 'PLAN_A_ACCEPTED' || e.event_type === 'PLAN_B_ACCEPTED' ? index : last, -1);
    return events.slice(accepted + 1).some(e => e.event_type === 'WORLD_STATE_CHANGED' || e.event_type === 'SEGMENTS_INVALIDATED');
  });
  readonly pendingNotificationMode = signal<NotificationMode>('decisions_only');
  readonly careWindow = signal<CoverageWindow | null>(null);
  constructor() {
    // Presentation only: this request must never gate or fail the recovery mutation.
    inject(FamilyService).get().pipe(takeUntilDestroyed()).subscribe({
      next: family => {
        this.pendingNotificationMode.set(family.notification_mode);
        this.careWindow.set(family.required_care_schedule);
        this.store.demoCareDate.set(family.required_care_schedule.start);
      },
      error: () => this.pendingNotificationMode.set('decisions_only'),
    });
  }

  private segmentsMateriallyMatch(left: CoverageSegment, right: CoverageSegment): boolean {
    const segmentType = (segment: CoverageSegment) => segment.segment_type ?? 'CARE';
    const location = (segment: CoverageSegment) =>
      segment.location_id ?? segment.location_label ?? null;
    const destination = (segment: CoverageSegment) =>
      segment.destination_location_id ?? segment.destination_location_label ?? null;
    const transporter = (segment: CoverageSegment) =>
      segment.transporter_id ?? segment.assigned_person_id;

    return (
      Date.parse(left.window.start) === Date.parse(right.window.start) &&
      Date.parse(left.window.end) === Date.parse(right.window.end) &&
      left.assigned_person_id === right.assigned_person_id &&
      left.source === right.source &&
      segmentType(left) === segmentType(right) &&
      location(left) === location(right) &&
      (segmentType(left) !== 'TRANSPORT' ||
        (destination(left) === destination(right) && transporter(left) === transporter(right)))
    );
  }

  private stringList(event: RecoveryEvent, key: string): string[] {
    const value = event.details[key];
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
  }

  private coverageWindows(event: RecoveryEvent): CoverageWindow[] {
    const value = event.details['uncovered_windows'];
    if (!Array.isArray(value)) return [];
    return value.filter((item): item is CoverageWindow => {
      if (!item || typeof item !== 'object') return false;
      const candidate = item as Record<string, unknown>;
      return (
        typeof candidate['start'] === 'string' &&
        typeof candidate['end'] === 'string' &&
        Date.parse(candidate['start']) < Date.parse(candidate['end'])
      );
    });
  }
}
