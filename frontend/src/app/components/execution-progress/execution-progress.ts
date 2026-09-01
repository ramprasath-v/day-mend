import { Component, computed, input } from '@angular/core';

import { ExecutionAction, RecoveryCase } from '../../core/recovery.models';

interface ActionGroup {
  label: string;
  description: string;
  actions: ExecutionAction[];
}

@Component({
  selector: 'app-execution-progress',
  templateUrl: './execution-progress.html',
  styleUrl: './execution-progress.css',
})
export class ExecutionProgressComponent {
  readonly recovery = input.required<RecoveryCase>();
  readonly groups = computed<ActionGroup[]>(() => {
    const actions = this.recovery().execution_actions;
    return [
      {
        label: 'Calendar changes',
        description: 'Work commitments adjusted',
        actions: actions.filter((action) => action.action_type === 'UPDATE_CALENDAR'),
      },
      {
        label: 'Backup coverage',
        description: 'Caregiver reservations confirmed',
        actions: actions.filter((action) => action.action_type === 'RESERVE_CAREGIVER'),
      },
      {
        label: 'Final verification',
        description: 'Full childcare coverage rechecked',
        actions: [],
      },
    ];
  });
  completed(group: ActionGroup): boolean {
    return group.label === 'Final verification'
      ? this.recovery().status === 'RESOLVED'
      : group.actions.length > 0 && group.actions.every((action) => action.status === 'SUCCEEDED');
  }
}
