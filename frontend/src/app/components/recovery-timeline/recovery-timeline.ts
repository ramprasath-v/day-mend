import { DatePipe } from '@angular/common';
import { Component, computed, input } from '@angular/core';

import { RecoveryCase } from '../../core/recovery.models';

interface TimelineItem {
  id: string;
  time: string;
  title: string;
  detail: string;
  state: 'done' | 'changed' | 'pending';
}

@Component({
  selector: 'app-recovery-timeline',
  imports: [DatePipe],
  templateUrl: './recovery-timeline.html',
  styleUrl: './recovery-timeline.css',
})
export class RecoveryTimelineComponent {
  readonly recovery = input.required<RecoveryCase>();
  readonly items = computed<TimelineItem[]>(() => {
    const recovery = this.recovery();
    const events = recovery.events;
    const items: TimelineItem[] = [];
    const disruption = events.find((event) => event.event_type === 'DISRUPTION_DETECTED');
    if (disruption) {
      items.push({
        id: disruption.event_id,
        time: disruption.occurred_at,
        title: 'Nanny reported sick',
        detail: 'Today’s normal childcare became unavailable.',
        state: 'changed',
      });
    }
    items.push({
      id: 'initial-plan',
      time: recovery.timestamps.created_at,
      title: recovery.previous_plans.length ? 'Recovery Plan A created' : 'Recovery plan created',
      detail: 'Calendars, trusted caregivers, coverage, and cost were checked.',
      state: 'done',
    });
    const decline = events.find((event) => event.event_type === 'CAREGIVER_DECLINED');
    if (decline) {
      items.push({
        id: decline.event_id,
        time: decline.occurred_at,
        title: 'Grandma declined',
        detail: 'The dependent Plan A coverage was marked unavailable.',
        state: 'changed',
      });
      items.push({
        id: 'replan',
        time: recovery.timestamps.updated_at,
        title: 'DayMend rebuilt the affected coverage',
        detail: `${recovery.plan_history.length} earlier plan retained for a complete audit trail.`,
        state: 'done',
      });
    }
    const requested = events.find((event) => event.event_type === 'APPROVAL_REQUESTED');
    if (requested) {
      items.push({
        id: requested.event_id,
        time: requested.occurred_at,
        title: 'Approval required',
        detail: 'The valid plan crossed the family’s automatic-spend limit.',
        state: recovery.pending_approval ? 'pending' : 'done',
      });
    }
    const approved = events.find((event) => event.event_type === 'APPROVAL_APPROVED');
    const rejected = events.find((event) => event.event_type === 'APPROVAL_REJECTED');
    if (approved || rejected) {
      const decision = approved ?? rejected!;
      items.push({
        id: decision.event_id,
        time: decision.occurred_at,
        title: approved ? 'Parent approved the recovery' : 'Parent declined the recovery cost',
        detail: approved
          ? 'DayMend resumed the same recovery case.'
          : 'No recovery actions were executed.',
        state: approved ? 'done' : 'changed',
      });
    }
    if (recovery.execution_actions.length) {
      const succeeded = recovery.execution_actions.filter(
        (action) => action.status === 'SUCCEEDED',
      );
      items.push({
        id: 'actions',
        time: recovery.timestamps.updated_at,
        title: `${succeeded.length} recovery actions completed`,
        detail: 'Calendar changes and backup coverage were confirmed.',
        state: succeeded.length === recovery.execution_actions.length ? 'done' : 'pending',
      });
    }
    if (recovery.status === 'RESOLVED') {
      items.push({
        id: 'resolved',
        time: recovery.timestamps.completion_verified_at ?? recovery.timestamps.updated_at,
        title: 'Day recovered',
        detail: 'Full childcare coverage passed deterministic final verification.',
        state: 'done',
      });
    }
    return items;
  });
}
