import { Component, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FamilyService, NotificationMode } from '../core/family.service';
import { DatePipe } from '@angular/common';
import { RecoveryStore } from '../core/recovery.store';
import { ApprovalCardComponent } from '../components/approval-card/approval-card';
import { CoveragePlanComponent } from '../components/coverage-plan/coverage-plan';
import { DemoControlsComponent } from '../components/demo-controls/demo-controls';
import { LiveRecoveryComponent } from '../components/live-recovery/live-recovery';
import { PlanChangeComponent } from '../components/plan-change/plan-change';
import { RecoveryHeroComponent } from '../components/recovery-hero/recovery-hero';

@Component({
  selector: 'app-today',
  imports: [DatePipe, ApprovalCardComponent, CoveragePlanComponent, DemoControlsComponent, LiveRecoveryComponent, PlanChangeComponent, RecoveryHeroComponent],
  templateUrl: './today.html',
  styleUrl: './today.css',
})
export class TodayPage {
  readonly store = inject(RecoveryStore);
  readonly pendingNotificationMode = signal<NotificationMode>('decisions_only');
  constructor() {
    // Presentation only: this request must never gate or fail the recovery mutation.
    inject(FamilyService).get().pipe(takeUntilDestroyed()).subscribe({
      next: family => this.pendingNotificationMode.set(family.notification_mode),
      error: () => this.pendingNotificationMode.set('decisions_only'),
    });
  }
}
