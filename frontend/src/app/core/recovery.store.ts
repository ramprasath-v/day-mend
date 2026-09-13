import { computed, inject, Injectable, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { finalize } from 'rxjs';

import { RecoveryApiService } from './recovery-api.service';
import { FamilyService } from './family.service';
import { RecoveryProgressService } from './recovery-progress.service';
import { ApprovalDecisionRequest, RecoveryCase, RecoveryProgressEvent } from './recovery.models';

export type RecoveryAction =
  | 'starting'
  | 'declining'
  | 'approving'
  | 'rejecting'
  | 'refreshing'
  | 'resetting';

@Injectable({ providedIn: 'root' })
export class RecoveryStore {
  private readonly storageKey = 'daymend.recoveryCaseId';
  private readonly api = inject(RecoveryApiService);
  private readonly family = inject(FamilyService);
  private readonly progress = inject(RecoveryProgressService);
  private progressId: string | null = null;
  private disconnectProgress: (() => void) | null = null;
  private elapsedTimer: ReturnType<typeof setInterval> | null = null;
  private actionStartedAt = 0;

  readonly currentCase = signal<RecoveryCase | null>(null);
  readonly currentCaseId = computed(() => this.currentCase()?.recovery_case_id ?? null);
  readonly actionInProgress = signal<RecoveryAction | null>(null);
  readonly loading = computed(() => this.actionInProgress() !== null);
  readonly error = signal<string | null>(null);
  readonly progressEvents = signal<RecoveryProgressEvent[]>([]);
  readonly progressConnected = signal(false);
  readonly elapsedSeconds = signal(0);
  readonly demoCareDate = signal<string | null>(null);

  constructor() {
    const storedCaseId = globalThis.localStorage?.getItem(this.storageKey);
    if (storedCaseId) {
      this.ensureProgress(storedCaseId);
      this.run('refreshing', () => this.api.getRecovery(storedCaseId));
    }
  }

  readonly loadingMessage = computed(() => {
    const messages: Record<RecoveryAction, string> = {
      starting: 'Checking today’s schedule and trusted backup options…',
      declining: 'Adapting the plan to Grandma’s response…',
      approving: 'Confirming backup coverage and verifying the recovery…',
      rejecting: 'Recording your decision…',
      refreshing: 'Refreshing the recovery state…',
      resetting: 'Resetting the demo family…',
    };
    const action = this.actionInProgress();
    return action ? messages[action] : '';
  });

  startRecovery(): void {
    const progressId = this.ensureProgress();
    this.run('starting', () =>
      this.api.startRecovery({
        disruption_type: 'CHILDCARE_UNAVAILABLE',
        occurred_at: new Date().toISOString(),
        caregiver_id: 'nanny',
        message: "I'm sick and can't come today.",
      }, progressId),
    );
  }

  submitGrandmaDecline(): void {
    const recovery = this.currentCase();
    if (!recovery) return;
    const dependentSegments = recovery.active_plan?.coverage_segments.filter(
      (segment) =>
        segment.assigned_person_id === 'grandma' || segment.transporter_id === 'grandma',
    );
    if (!dependentSegments?.length) return;
    const progressId = this.ensureProgress(recovery.recovery_case_id);
    const starts = dependentSegments.map((segment) => segment.window.start).sort();
    const ends = dependentSegments.map((segment) => segment.window.end).sort();
    this.run('declining', () =>
      this.api.submitEvent(recovery.recovery_case_id, {
        event_type: 'CAREGIVER_DECLINED',
        caregiver_id: 'grandma',
        occurred_at: new Date().toISOString(),
        relevant_window: {
          start: starts[0],
          end: ends.at(-1)!,
        },
        message: "Sorry, I can't help today.",
        expected_version: recovery.version,
      }, progressId),
    );
  }

  decideApproval(decision: 'APPROVE' | 'REJECT'): void {
    const recovery = this.currentCase();
    const approval = recovery?.pending_approval;
    if (!recovery || !approval) return;
    const progressId = this.ensureProgress(recovery.recovery_case_id);
    const request: ApprovalDecisionRequest = {
      decision,
      expected_version: recovery.version,
      ...(decision === 'REJECT' ? { reason: 'Parent declined recovery cost' } : {}),
    };
    this.run(
      decision === 'APPROVE' ? 'approving' : 'rejecting',
      () =>
        this.api.decideApproval(
          recovery.recovery_case_id,
          approval.approval_id,
          request,
          progressId,
        ),
      (result) => this.approvalResponseError(result, approval.approval_id, decision),
    );
  }

  refresh(): void {
    const caseId = this.currentCaseId();
    if (!caseId) return;
    this.run('refreshing', () => this.api.getRecovery(caseId));
  }

  resetDemo(): void {
    if (this.loading()) return;
    this.error.set(null);
    this.actionInProgress.set('resetting');
    this.family
      .resetDemo()
      .pipe(finalize(() => this.actionInProgress.set(null)))
      .subscribe({
        next: (profile) => {
          this.demoCareDate.set(profile.required_care_schedule.start);
          this.currentCase.set(null);
          this.progressEvents.set([]);
          this.stopProgress();
          this.progressId = null;
          globalThis.localStorage?.removeItem(this.storageKey);
        },
        error: () =>
          this.error.set('DayMend could not reset the demo family. Your saved recovery is unchanged.'),
      });
  }

  private run(
    action: RecoveryAction,
    request: () => ReturnType<RecoveryApiService['getRecovery']>,
    responseError?: (recovery: RecoveryCase) => string | null,
  ): void {
    if (this.loading()) return;
    this.error.set(null);
    this.actionInProgress.set(action);
    this.startElapsedTimer();
    request()
      .pipe(
        finalize(() => {
          this.actionInProgress.set(null);
          this.stopElapsedTimer();
          this.refreshProgressSnapshot();
        }),
      )
      .subscribe({
        next: (recovery) => {
          const error = responseError?.(recovery);
          if (error) {
            this.error.set(error);
            return;
          }
          this.currentCase.set(recovery);
          globalThis.localStorage?.setItem(this.storageKey, recovery.recovery_case_id);
        },
        error: (error: HttpErrorResponse) => this.error.set(this.safeMessage(error, action)),
      });
  }

  private ensureProgress(recoveryCaseId?: string): string {
    if (this.progressId) return this.progressId;
    this.progressId = recoveryCaseId ?? this.newProgressId();
    this.disconnectProgress = this.progress.connect(
      this.progressId,
      (event) => this.mergeProgress([event]),
      (connected) => this.progressConnected.set(connected),
    );
    return this.progressId;
  }

  private refreshProgressSnapshot(): void {
    if (!this.progressId) return;
    this.api.getProgress(this.progressId).subscribe({
      next: (events) => this.mergeProgress(events),
      error: () => undefined,
    });
  }

  private mergeProgress(incoming: RecoveryProgressEvent[]): void {
    this.progressEvents.update((current) => {
      const byId = new Map(current.map((event) => [event.id, event]));
      incoming.forEach((event) => byId.set(event.id, event));
      return [...byId.values()].sort((left, right) => left.sequence - right.sequence);
    });
  }

  private startElapsedTimer(): void {
    this.stopElapsedTimer();
    this.actionStartedAt = Date.now();
    this.elapsedSeconds.set(0);
    this.elapsedTimer = setInterval(
      () => this.elapsedSeconds.set(Math.floor((Date.now() - this.actionStartedAt) / 1000)),
      1000,
    );
  }

  private stopElapsedTimer(): void {
    if (this.elapsedTimer !== null) clearInterval(this.elapsedTimer);
    this.elapsedTimer = null;
  }

  private stopProgress(): void {
    this.disconnectProgress?.();
    this.disconnectProgress = null;
    this.progressConnected.set(false);
  }

  private newProgressId(): string {
    return globalThis.crypto?.randomUUID?.() ?? `daymend-${Date.now()}-${Math.random()}`;
  }

  private approvalResponseError(
    recovery: RecoveryCase,
    approvalId: string,
    decision: 'APPROVE' | 'REJECT',
  ): string | null {
    const approval = recovery.approval_history.find(
      (item) => item.approval_id === approvalId,
    );
    const expectedStatus = decision === 'APPROVE' ? 'APPROVED' : 'REJECTED';
    const validDecision = approval?.status === expectedStatus;
    const validRejection =
      decision !== 'REJECT' ||
      (recovery.status === 'REPLANNING' &&
        recovery.execution_actions.length === 0 &&
        recovery.timestamps.completion_verified_at === null);
    return validDecision && validRejection
      ? null
      : 'DayMend received an inconsistent approval result. Refresh before taking another action.';
  }

  private safeMessage(error: HttpErrorResponse, action: RecoveryAction): string {
    const code = error.error?.error?.code as string | undefined;
    if (code === 'STALE_APPROVAL' || code === 'APPROVAL_ALREADY_FINALIZED') {
      return 'That approval is no longer current. Refresh the recovery and try again.';
    }
    if (code === 'PLANNING_FAILED') {
      return "We couldn't build a safe recovery plan.";
    }
    if (
      code === 'REPLANNING_FAILED' ||
      (action === 'declining' && code === 'INTERNAL_ERROR')
    ) {
      return "DayMend couldn't complete replanning. Please try again.";
    }
    if (code === 'PERSISTENCE_CONFLICT') {
      return 'This recovery changed elsewhere. Refresh to see the latest state.';
    }
    return error.status === 0
      ? 'Unable to reach DayMend. Check that the backend is running.'
      : "DayMend couldn't complete that request. Please try again.";
  }
}
