import { Component, inject } from '@angular/core';

import { ApprovalCardComponent } from './components/approval-card/approval-card';
import { CoveragePlanComponent } from './components/coverage-plan/coverage-plan';
import { DemoControlsComponent } from './components/demo-controls/demo-controls';
import { LiveRecoveryComponent } from './components/live-recovery/live-recovery';
import { PlanChangeComponent } from './components/plan-change/plan-change';
import { RecoveryHeroComponent } from './components/recovery-hero/recovery-hero';
import { RecoveryStore } from './core/recovery.store';

@Component({
  selector: 'app-root',
  imports: [
    ApprovalCardComponent,
    CoveragePlanComponent,
    DemoControlsComponent,
    LiveRecoveryComponent,
    PlanChangeComponent,
    RecoveryHeroComponent,
  ],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App {
  readonly store = inject(RecoveryStore);
}
