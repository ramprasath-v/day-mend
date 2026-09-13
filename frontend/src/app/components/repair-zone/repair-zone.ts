import { Component, computed, input } from '@angular/core';
import { DatePipe } from '@angular/common';
import { RecoveryPlan, CoverageSegment, CoverageWindow } from '../../core/recovery.models';
import { friendlyPerson } from '../../core/recovery-status';

/** Presentation of the submitted decline, never a replacement planning decision. */
@Component({
  selector: 'app-repair-zone',
  imports: [DatePipe],
  templateUrl: './repair-zone.html',
  styleUrl: './repair-zone.css',
})
export class RepairZoneComponent {
  readonly plan = input.required<RecoveryPlan>();
  readonly personId = input.required<string>();
  readonly confirmed = input(false);
  readonly friendlyPerson = friendlyPerson;
  readonly segments = computed(() => [...this.plan().coverage_segments].sort((a,b) => Date.parse(a.window.start) - Date.parse(b.window.start)));
  readonly affected = computed(() => this.segments().filter(s => s.assigned_person_id === this.personId() || s.transporter_id === this.personId()));
  readonly windows = computed(() => {
    const windows: CoverageWindow[] = [];
    for (const segment of this.affected()) {
      const last = windows.at(-1);
      if (last && Date.parse(segment.window.start) <= Date.parse(last.end)) {
        if (Date.parse(segment.window.end) > Date.parse(last.end)) last.end = segment.window.end;
      } else windows.push({ ...segment.window });
    }
    return windows;
  });
  readonly locations = computed(() => new Set(this.affected().filter(s => s.segment_type !== 'TRANSPORT').map(s => s.location_id).filter(Boolean)));
  needsReview(segment: CoverageSegment): boolean {
    return segment.segment_type === 'TRANSPORT' && !!segment.destination_location_id && this.locations().has(segment.destination_location_id);
  }
  label(segment: CoverageSegment): string {
    if (this.affected().includes(segment)) return this.confirmed() ? 'Unavailable · replacement needed' : 'Decline being sent · awaiting confirmation';
    if (this.needsReview(segment)) return 'Handoff needs review';
    return 'Unchanged in the current plan';
  }
  location(segment: CoverageSegment): string {
    const origin = segment.location_label ?? friendlyPerson(segment.location_id ?? '');
    const destination = segment.destination_location_label ?? friendlyPerson(segment.destination_location_id ?? '');
    return segment.segment_type === 'TRANSPORT' ? origin + ' → ' + destination : origin;
  }
}
