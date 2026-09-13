import { DatePipe } from '@angular/common';
import { Component, computed, input } from '@angular/core';

import { CoverageSegment, RecoveryCase } from '../../core/recovery.models';
import { friendlyPerson } from '../../core/recovery-status';

@Component({
  selector: 'app-plan-change',
  imports: [DatePipe],
  templateUrl: './plan-change.html',
  styleUrl: './plan-change.css',
})
export class PlanChangeComponent {
  readonly recovery = input.required<RecoveryCase>();
  readonly priorPlan = computed(() => this.recovery().previous_plans.at(-1) ?? null);
  readonly latestApproval = computed(() => this.recovery().approval_history.at(-1) ?? null);
  readonly rejected = computed(() => this.latestApproval()?.status === 'REJECTED');
  readonly applied = computed(() => {
    const recovery = this.recovery();
    return (
      recovery.status === 'RESOLVED' ||
      (this.latestApproval()?.status === 'APPROVED' &&
        recovery.execution_actions.length > 0 &&
        recovery.execution_actions.every((action) => action.status === 'SUCCEEDED'))
    );
  });
  readonly heading = computed(() => {
    if (this.rejected()) return 'Proposed alternative — not applied';
    return this.applied() ? 'Your day, repaired.' : 'Proposed repair';
  });
  readonly description = computed(() => {
    if (this.rejected()) {
      return 'This proposal was declined and is shown only for context.';
    }
    if (this.applied()) {
      return 'DayMend kept the coverage that still worked and adjusted the affected care and handoffs.';
    }
    return 'DayMend kept the coverage that still works. Nothing changes until you approve this proposal.';
  });
  readonly afterColumnLabel = computed(() => (this.applied() ? 'Now' : 'Proposed'));
  readonly affected = computed(() => this.partitionSegments().affected);
  readonly preserved = computed(() => this.partitionSegments().preserved);
  readonly replacement = computed(() => {
    const affected = this.affected();
    const priorSegments = this.priorPlan()?.coverage_segments ?? [];
    return (this.recovery().active_plan?.coverage_segments ?? []).filter(
      (segment) =>
        !priorSegments.some((prior) => this.segmentsMateriallyMatch(prior, segment)) &&
        affected.some(
          (prior) =>
            new Date(segment.window.start) < new Date(prior.window.end) &&
            new Date(prior.window.start) < new Date(segment.window.end),
        ),
    );
  });
  readonly friendlyPerson = friendlyPerson;
  readonly groups = computed(() => {
    const before = this.priorPlan()?.coverage_segments ?? [];
    const after = this.recovery().active_plan?.coverage_segments ?? [];
    const entries = [...before.map(segment => ({ segment, side: 'before' as const })), ...after.map(segment => ({ segment, side: 'after' as const }))]
      .sort((a, b) => Date.parse(a.segment.window.start) - Date.parse(b.segment.window.start));
    const groups: { start: number; end: number; before: CoverageSegment[]; after: CoverageSegment[]; kept: boolean }[] = [];
    for (const entry of entries) {
      const start = Date.parse(entry.segment.window.start);
      const end = Date.parse(entry.segment.window.end);
      let group = groups.at(-1);
      if (!group || start >= group.end) {
        group = { start, end, before: [], after: [], kept: false };
        groups.push(group);
      }
      group.end = Math.max(group.end, end);
      group[entry.side].push(entry.segment);
    }
    return groups.map(group => ({ ...group, kept: group.before.length === 1 && group.after.length === 1 && this.segmentsMateriallyMatch(group.before[0], group.after[0]) }));
  });

  classification(segment: CoverageSegment): string {
    if (this.affected().includes(segment)) return 'Unavailable';
    const active = this.recovery().active_plan;
    if (segment.segment_type !== 'TRANSPORT' || active?.validation_state !== 'VALID') return 'Changed';
    const overlapping = active.coverage_segments.filter(other => Date.parse(other.window.start) < Date.parse(segment.window.end) && Date.parse(other.window.end) > Date.parse(segment.window.start))
      .sort((a, b) => Date.parse(a.window.start) - Date.parse(b.window.start));
    let coveredUntil = Date.parse(segment.window.start);
    for (const other of overlapping) {
      if (other.segment_type === 'TRANSPORT' || Date.parse(other.window.start) > coveredUntil) return 'Changed';
      coveredUntil = Math.max(coveredUntil, Date.parse(other.window.end));
    }
    return coveredUntil >= Date.parse(segment.window.end) ? 'Transport no longer needed' : 'Changed';
  }

  afterLabel(segment: CoverageSegment): string {
    if (this.replacement().includes(segment)) return 'Replacement';
    return this.priorPlan()?.coverage_segments.some(prior => this.segmentsMateriallyMatch(prior, segment)) ? 'Kept' : 'Updated';
  }

  location(segment: CoverageSegment): string {
    const origin = segment.location_label ?? (segment.location_id ? friendlyPerson(segment.location_id) : '');
    const destination = segment.destination_location_label ?? (segment.destination_location_id ? friendlyPerson(segment.destination_location_id) : null);
    return segment.segment_type === 'TRANSPORT' && destination ? origin + ' → ' + destination : origin;
  }

  segmentLabel(segment: CoverageSegment): string {
    return segment.segment_type === 'TRANSPORT'
      ? `Transport with ${friendlyPerson(segment.transporter_id ?? segment.assigned_person_id)}`
      : friendlyPerson(segment.assigned_person_id);
  }

  private partitionSegments(): { affected: CoverageSegment[]; preserved: CoverageSegment[] } {
    const segments = this.priorPlan()?.coverage_segments ?? [];
    const activeSegments = this.recovery().active_plan?.coverage_segments ?? [];
    const assumptions = this.recovery().invalidated_assumptions;
    const affected = segments.filter((segment) =>
      assumptions.some(
        (assumption) =>
          (assumption.subject_id === segment.assigned_person_id ||
            assumption.subject_id === segment.transporter_id) &&
          assumption.relevant_window &&
          new Date(segment.window.start) < new Date(assumption.relevant_window.end) &&
          new Date(assumption.relevant_window.start) < new Date(segment.window.end),
      ),
    );
    return {
      affected,
      preserved: segments.filter((segment) =>
        activeSegments.some((active) => this.segmentsMateriallyMatch(segment, active)),
      ),
    };
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
      new Date(left.window.start).getTime() === new Date(right.window.start).getTime() &&
      new Date(left.window.end).getTime() === new Date(right.window.end).getTime() &&
      left.assigned_person_id === right.assigned_person_id &&
      left.source === right.source &&
      segmentType(left) === segmentType(right) &&
      location(left) === location(right) &&
      (segmentType(left) !== 'TRANSPORT' ||
        (destination(left) === destination(right) && transporter(left) === transporter(right)))
    );
  }
}
