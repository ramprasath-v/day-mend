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
  readonly showActivitySummary = computed(() =>
    (this.recovery()?.notification_mode ?? this.pendingNotificationMode()) === 'meaningful_changes');
  readonly showStatusSummary = computed(() => {
    const recovery = this.recovery();
    const mode = recovery?.notification_mode ?? this.pendingNotificationMode();
    // Never hide a pending operation, required decision, or failure.
    if (this.busy() || this.error() || recovery?.pending_approval
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
    if (recovery?.approval_history.at(-1)?.status === 'REJECTED') return 'Recovery not approved';
    if (recovery?.status === 'RESOLVED') return 'Recovery resolved';
    if (recovery?.pending_approval || recovery?.status === 'APPROVAL_REQUIRED') return 'Awaiting approval';
    if (recovery?.status === 'EXECUTING') return 'Executing recovery';
    if (recovery?.status === 'FAILED') return 'Recovery needs attention';
    if (recovery?.status === 'WAITING_FOR_RESPONSE') return 'Planning finished';
    return 'Recovery paused';
  });
}
