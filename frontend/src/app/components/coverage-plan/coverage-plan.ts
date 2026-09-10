import { CurrencyPipe, DatePipe } from '@angular/common';
import { Component, computed, input } from '@angular/core';

import {
  CoverageSegment,
  InvalidatedAssumption,
  MoneyValue,
  RecoveryPlan,
} from '../../core/recovery.models';
import { friendlyPerson } from '../../core/recovery-status';

@Component({
  selector: 'app-coverage-plan',
  imports: [CurrencyPipe, DatePipe],
  templateUrl: './coverage-plan.html',
  styleUrl: './coverage-plan.css',
})
export class CoveragePlanComponent {
  readonly plan = input.required<RecoveryPlan>();
  readonly title = input("Today's recovery plan");
  readonly badge = input('Current plan');
  readonly automaticSpendLimit = input<MoneyValue | null>(null);
  readonly previousPlan = input<RecoveryPlan | null>(null);
  readonly invalidatedAssumptions = input<InvalidatedAssumption[]>([]);
  readonly requiresApproval = input(false);
  readonly friendlyPerson = friendlyPerson;
  readonly money = Number;
  readonly careAtHome = computed(() => {
    const care = this.plan().coverage_segments.filter(
      (segment) => segment.segment_type !== 'TRANSPORT',
    );
    return care.length > 0 && care.every((segment) => segment.location_id === 'family_home');
  });
  readonly transportCount = computed(
    () =>
      this.plan().coverage_segments.filter((segment) => segment.segment_type === 'TRANSPORT')
        .length,
  );
  readonly coverageEnd = computed(
    () => this.plan().coverage_segments.at(-1)?.window.end ?? null,
  );
  readonly replacementRecommendation = computed(() => {
    const previousPlan = this.previousPlan();
    if (!previousPlan) return null;
    const previousCaregivers = new Set(
      previousPlan.coverage_segments
        .filter((segment) => segment.source === 'CAREGIVER')
        .map((segment) => segment.assigned_person_id),
    );
    const affectedWindows = this.invalidatedAssumptions()
      .map((assumption) => assumption.relevant_window)
      .filter((window) => window !== null);
    const replacementSegments = this.plan().coverage_segments.filter(
      (segment) =>
        segment.source === 'CAREGIVER' &&
        !previousCaregivers.has(segment.assigned_person_id) &&
        affectedWindows.some(
          (window) =>
            new Date(segment.window.start) < new Date(window.end) &&
            new Date(window.start) < new Date(segment.window.end),
        ),
    );
    const caregiverId = replacementSegments[0]?.assigned_person_id;
    if (!caregiverId) return null;
    const caregiverSegments = replacementSegments.filter(
      (segment) => segment.assigned_person_id === caregiverId,
    );
    const starts = caregiverSegments.map((segment) => segment.window.start).sort();
    const ends = caregiverSegments.map((segment) => segment.window.end).sort();
    const inHome = caregiverSegments.every((segment) => segment.location_id === 'family_home');
    const locations = [
      ...new Set(
        caregiverSegments
          .map((segment) => segment.location_label)
          .filter((label): label is string => !!label),
      ),
    ];
    return {
      caregiverId,
      start: starts[0],
      end: ends.at(-1)!,
      cost: caregiverSegments.reduce(
        (total, segment) => total + Number(segment.estimated_cost),
        0,
      ),
      location: inHome
        ? `In-home care${locations.length ? ` · ${locations.join(', ')}` : ''}`
        : locations.join(', ') || 'Location recorded in plan',
    };
  });

  location(segment: CoverageSegment): string {
    if (segment.segment_type === 'TRANSPORT') {
      const origin = segment.location_label ?? 'Start';
      const destination = segment.destination_location_label ?? 'Destination';
      return `${origin} → ${destination}`;
    }
    return segment.location_label ?? 'Location recorded in plan';
  }
}
