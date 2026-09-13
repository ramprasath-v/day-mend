import { Component, computed, inject } from '@angular/core';
import { CurrencyPipe, DatePipe } from '@angular/common';
import { RecoveryStore } from '../core/recovery.store';
import { RECOVERY_STATUS_COPY, friendlyPerson } from '../core/recovery-status';
import { CoverageSegment } from '../core/recovery.models';
import { PlanChangeComponent } from '../components/plan-change/plan-change';
import { CoveragePlanComponent } from '../components/coverage-plan/coverage-plan';
import { LiveRecoveryComponent } from '../components/live-recovery/live-recovery';

@Component({
  selector: 'app-history',
  imports: [CurrencyPipe, DatePipe, PlanChangeComponent, CoveragePlanComponent, LiveRecoveryComponent],
  templateUrl: './history.html',
  styleUrl: './history.css',
})
export class HistoryPage {
  readonly store = inject(RecoveryStore);
  readonly copy = RECOVERY_STATUS_COPY;
  readonly friendlyPerson = friendlyPerson;
  readonly rejected = computed(
    () => this.store.currentCase()?.approval_history.at(-1)?.status === 'REJECTED',
  );
  readonly careDate = computed(() => {
    const segments = this.store.currentCase()?.active_plan?.coverage_segments ?? [];
    return [...segments].sort((a,b) => Date.parse(a.window.start) - Date.parse(b.window.start))[0]?.window.start;
  });
  readonly kept = computed(() => {
    const recovery = this.store.currentCase();
    return (recovery?.active_plan?.coverage_segments ?? []).filter(s =>
      recovery?.previous_plans.at(-1)?.coverage_segments.some(p => this.same(p, s)));
  });
  readonly changed = computed(() => {
    const recovery = this.store.currentCase();
    if (!recovery?.previous_plans.length) return [];
    return (recovery.active_plan?.coverage_segments ?? []).filter(s => !this.kept().includes(s));
  });
  readonly changes = computed(() => this.store.currentCase()?.events.filter(e => e.event_type === 'CAREGIVER_DECLINED') ?? []);
  readonly result = computed(() => {
    const recovery = this.store.currentCase();
    if (!recovery) return '';
    if (recovery.status === 'RESOLVED') return 'Recovered';
    if (recovery.approval_history.at(-1)?.status === 'REJECTED') return 'Not approved';
    return this.copy[recovery.status].eyebrow;
  });
  same(a: CoverageSegment, b: CoverageSegment): boolean {
    return Date.parse(a.window.start) === Date.parse(b.window.start) && Date.parse(a.window.end) === Date.parse(b.window.end)
      && a.assigned_person_id === b.assigned_person_id && a.source === b.source
      && (a.segment_type ?? 'CARE') === (b.segment_type ?? 'CARE')
      && (a.location_id ?? a.location_label ?? null) === (b.location_id ?? b.location_label ?? null)
      && (a.segment_type !== 'TRANSPORT' || (
        (a.transporter_id ?? a.assigned_person_id) === (b.transporter_id ?? b.assigned_person_id)
        && (a.destination_location_id ?? a.destination_location_label ?? null) === (b.destination_location_id ?? b.destination_location_label ?? null)));
  }
}
