import { Component, inject } from '@angular/core';

import { ApprovalCardComponent } from './components/approval-card/approval-card';
import { CoveragePlanComponent } from './components/coverage-plan/coverage-plan';
import { DemoControlsComponent } from './components/demo-controls/demo-controls';
import { ExecutionProgressComponent } from './components/execution-progress/execution-progress';
import { PlanChangeComponent } from './components/plan-change/plan-change';
import { RecoveryHeroComponent } from './components/recovery-hero/recovery-hero';
import { RecoveryTimelineComponent } from './components/recovery-timeline/recovery-timeline';
import { ResolvedSummaryComponent } from './components/resolved-summary/resolved-summary';
import { RecoveryStore } from './core/recovery.store';

@Component({
  selector: 'app-root',
  imports: [
    ApprovalCardComponent,
    CoveragePlanComponent,
    DemoControlsComponent,
    ExecutionProgressComponent,
    PlanChangeComponent,
    RecoveryHeroComponent,
    RecoveryTimelineComponent,
    ResolvedSummaryComponent,
  ],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App {
  readonly store = inject(RecoveryStore);
}
