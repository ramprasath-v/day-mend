import { Component, computed, input } from '@angular/core';
import { DatePipe } from '@angular/common';
import { RecoveryCase, RecoveryProgressEvent } from '../../core/recovery.models';
import { NotificationMode } from '../../core/family.service';

@Component({
  selector: 'app-live-recovery',
  imports: [DatePipe],
  templateUrl: './live-recovery.html',
  styleUrl: './live-recovery.css',
})
export class LiveRecoveryComponent {
  readonly events = input<RecoveryProgressEvent[]>([]);
  readonly recovery = input<RecoveryCase | null>(null);
  readonly busy = input(false);
  readonly connected = input(false);
  readonly elapsedSeconds = input(0);
  readonly action = input<string | null>(null);
  readonly error = input<string | null>(null);
  readonly pendingNotificationMode = input<NotificationMode>('meaningful_changes');
  readonly journal = computed(() => [...this.events()].sort((a,b) => a.sequence - b.sequence));
  readonly completedActions = computed(() => this.recovery()?.execution_actions.filter(a => a.status === 'SUCCEEDED').length ?? 0);
  readonly currentEvents = computed(() => {
    const events = this.journal();
    if (this.action() !== 'declining') return events;
    const accepted = events.reduce((last, e, index) => ['PLAN_A_ACCEPTED', 'PLAN_B_ACCEPTED'].includes(e.event_type) ? index : last, -1);
    return events.slice(accepted + 1).filter(e => e.event_type !== 'APPROVAL_REQUIRED');
  });
  readonly phase = computed(() => {
    if (!this.busy() || this.error() || ['refreshing', 'rejecting'].includes(this.action() ?? '')) return this.status();
    if (!this.showActivitySummary()) return this.status();
    const latest = this.currentEvents().at(-1);
    if (this.action() === 'approving' && !latest?.event_type.startsWith('ACTION_') && !['EXECUTION_STARTED', 'COMPLETION_VERIFIED', 'RECOVERY_RESOLVED'].includes(latest?.event_type ?? '')) return 'Processing approval';
    return latest ? this.eventLabel(latest) : this.action() === 'declining'
      ? 'Sending the change — checking the affected care' : 'DayMend is working';
  });
  eventLabel(event: RecoveryProgressEvent): string {
    if (event.status === 'FAILED') return event.summary;
    const labels: Record<string, string> = {
      RECOVERY_STARTED: 'Change received', WORLD_STATE_CHANGED: 'Caregiver response received',
      ORCHESTRATOR_STARTED: 'Checking the day and people you know',
      DISRUPTION_ASSESSED: 'Care context received', REPLANNING_STARTED: 'Rebuilding the affected care and handoffs',
      SEGMENTS_INVALIDATED: 'Affected care needs a replacement', SEGMENTS_PRESERVED: 'Existing care preserved',
      KNOWN_OPTIONS_EXHAUSTED: 'Known care cannot cover the gap', RESEARCH_STARTED: 'Looking for backup care',
      RESEARCH_RESULTS_READY: 'Backup care options found', BACKUP_SELECTED: 'Replacement care recommended',
      PLANNER_STARTED: 'Building the revised day', PLAN_PROPOSED: 'A proposed day is ready to check',
      VALIDATION_STARTED: 'Checking timing, travel and cost', VALIDATION_FAILED: 'Adjusting the plan after checks',
      PLAN_REPAIR_STARTED: 'Repairing the plan before you see it', VALIDATION_PASSED: 'Plan passed timing, travel and cost checks',
      PLAN_A_ACCEPTED: 'Plan A is ready', PLAN_B_ACCEPTED: 'The repaired day is ready',
      APPROVAL_REQUIRED: 'One decision needs you', APPROVAL_APPROVED: 'You approved the recovery',
      APPROVAL_REJECTED: 'You declined — no actions taken', EXECUTION_STARTED: 'Putting the recovery into action',
      ACTION_SUCCEEDED: 'Recovery action completed', COMPLETION_VERIFIED: 'Final childcare coverage verified',
      RECOVERY_RESOLVED: 'Your day is recovered',
      NO_RECOVERY_OPTION: 'No recovery option with current settings',
    };
    return labels[event.event_type] ?? event.summary;
  }
  readonly showActivitySummary = computed(() =>
    (this.recovery()?.notification_mode ?? this.pendingNotificationMode()) === 'meaningful_changes');
  readonly showStatusSummary = computed(() => {
    const recovery = this.recovery();
    const mode = recovery?.notification_mode ?? this.pendingNotificationMode();
    // Never hide a pending operation, required decision, or failure.
    if (this.busy() || this.error() || recovery?.pending_approval
      || this.hasNoOption()
      || recovery?.approval_history.at(-1)?.status === 'REJECTED'
      || recovery?.status === 'FAILED' || recovery?.status === 'APPROVAL_REQUIRED') return true;
    return mode === 'meaningful_changes' || (mode === 'completion_only' && recovery?.status === 'RESOLVED');
  });
  readonly status = computed(() => {
    if (this.error()) return 'Recovery needs attention';
    if (this.busy()) {
      if (this.action() === 'refreshing') return 'Loading the saved recovery';
      if (this.action() === 'rejecting') return 'Recording your decision';
      const latest = this.events().at(-1);
      if (this.action() === 'approving') return latest?.actor_name === 'completion_verifier' ? 'Verifying completion' : 'Processing approval';
      return 'DayMend is rebuilding today’s plan';
    }
    const recovery = this.recovery();
    if (this.hasNoOption()) return 'No recovery option with current settings';
    if (recovery?.approval_history.at(-1)?.status === 'REJECTED') return 'Recovery not approved';
    if (recovery?.status === 'RESOLVED') return 'Recovery resolved';
    if (recovery?.pending_approval || recovery?.status === 'APPROVAL_REQUIRED') return 'Awaiting approval';
    if (recovery?.status === 'EXECUTING') return 'Executing recovery';
    if (recovery?.status === 'FAILED') return 'Recovery needs attention';
    if (recovery?.status === 'WAITING_FOR_RESPONSE') return 'Planning finished';
    return 'Recovery paused';
  });

  private hasNoOption(): boolean {
    return this.recovery()?.events.some(
      (event) => event.details['outcome_code'] === 'NO_RECOVERY_OPTION',
    ) ?? false;
  }
}
