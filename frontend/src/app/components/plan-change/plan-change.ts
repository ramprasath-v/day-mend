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
  readonly friendlyPerson = friendlyPerson;

  private partitionSegments(): { affected: CoverageSegment[]; preserved: CoverageSegment[] } {
    const segments = this.priorPlan()?.coverage_segments ?? [];
    const assumptions = this.recovery().invalidated_assumptions;
    const affected = segments.filter((segment) =>
      assumptions.some(
        (assumption) =>
          assumption.subject_id === segment.assigned_person_id &&
          assumption.relevant_window &&
          new Date(segment.window.start) < new Date(assumption.relevant_window.end) &&
          new Date(assumption.relevant_window.start) < new Date(segment.window.end),
      ),
    );
    const ids = new Set(affected.map((segment) => segment.segment_id));
    return { affected, preserved: segments.filter((segment) => !ids.has(segment.segment_id)) };
  }
}
