import { computed, inject, Injectable, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { finalize } from 'rxjs';

import { RecoveryApiService } from './recovery-api.service';
import { ApprovalDecisionRequest, RecoveryCase } from './recovery.models';

export type RecoveryAction = 'starting' | 'declining' | 'approving' | 'rejecting' | 'refreshing';

@Injectable({ providedIn: 'root' })
export class RecoveryStore {
  private readonly api = inject(RecoveryApiService);

  readonly currentCase = signal<RecoveryCase | null>(null);
  readonly currentCaseId = computed(() => this.currentCase()?.recovery_case_id ?? null);
  readonly actionInProgress = signal<RecoveryAction | null>(null);
  readonly loading = computed(() => this.actionInProgress() !== null);
  readonly error = signal<string | null>(null);

  readonly loadingMessage = computed(() => {
    const messages: Record<RecoveryAction, string> = {
      starting: 'Checking today’s schedule and trusted backup options…',
      declining: 'Adapting the plan to Grandma’s response…',
      approving: 'Confirming backup coverage and verifying the recovery…',
      rejecting: 'Recording your decision and looking for another option…',
      refreshing: 'Refreshing the recovery state…',
    };
    const action = this.actionInProgress();
    return action ? messages[action] : '';
  });

  startRecovery(): void {
    this.run('starting', () =>
      this.api.startRecovery({
        disruption_type: 'CHILDCARE_UNAVAILABLE',
        occurred_at: new Date().toISOString(),
        caregiver_id: 'nanny',
        message: "I'm sick and can't come today.",
      }),
    );
  }

  submitGrandmaDecline(): void {
    const recovery = this.currentCase();
    if (!recovery) return;
    this.run('declining', () =>
      this.api.submitEvent(recovery.recovery_case_id, {
        event_type: 'CAREGIVER_DECLINED',
        caregiver_id: 'grandma',
        occurred_at: new Date().toISOString(),
        relevant_window: {
          start: '2026-08-27T10:00:00-07:00',
          end: '2026-08-27T13:00:00-07:00',
        },
        message: "Sorry, I can't help today.",
        expected_version: recovery.version,
      }),
    );
  }

  decideApproval(decision: 'APPROVE' | 'REJECT'): void {
    const recovery = this.currentCase();
    const approval = recovery?.pending_approval;
    if (!recovery || !approval) return;
    const request: ApprovalDecisionRequest = {
      decision,
      expected_version: recovery.version,
      ...(decision === 'REJECT' ? { reason: 'Parent declined recovery cost' } : {}),
    };
    this.run(decision === 'APPROVE' ? 'approving' : 'rejecting', () =>
      this.api.decideApproval(recovery.recovery_case_id, approval.approval_id, request),
    );
  }

  refresh(): void {
    const caseId = this.currentCaseId();
    if (!caseId) return;
    this.run('refreshing', () => this.api.getRecovery(caseId));
  }

  private run(
    action: RecoveryAction,
    request: () => ReturnType<RecoveryApiService['getRecovery']>,
  ): void {
    if (this.loading()) return;
    this.error.set(null);
    this.actionInProgress.set(action);
    request()
      .pipe(finalize(() => this.actionInProgress.set(null)))
      .subscribe({
        next: (recovery) => this.currentCase.set(recovery),
        error: (error: HttpErrorResponse) => this.error.set(this.safeMessage(error)),
      });
  }

  private safeMessage(error: HttpErrorResponse): string {
    const code = error.error?.error?.code as string | undefined;
    if (code === 'STALE_APPROVAL' || code === 'APPROVAL_ALREADY_FINALIZED') {
      return 'That approval is no longer current. Refresh the recovery and try again.';
    }
    if (code === 'PLANNING_FAILED' || code === 'REPLANNING_FAILED') {
      return "DayMend couldn't complete this recovery plan.";
    }
    if (code === 'PERSISTENCE_CONFLICT') {
      return 'This recovery changed elsewhere. Refresh to see the latest state.';
    }
    return error.status === 0
      ? 'Unable to reach DayMend. Check that the backend is running.'
      : "DayMend couldn't complete that request. Please try again.";
  }
}
