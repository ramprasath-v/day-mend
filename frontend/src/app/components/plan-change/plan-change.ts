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
