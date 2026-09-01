import { CurrencyPipe, DatePipe } from '@angular/common';
import { Component, input } from '@angular/core';

import { RecoveryPlan } from '../../core/recovery.models';
import { friendlyPerson } from '../../core/recovery-status';

@Component({
  selector: 'app-coverage-plan',
  imports: [CurrencyPipe, DatePipe],
  templateUrl: './coverage-plan.html',
  styleUrl: './coverage-plan.css',
})
export class CoveragePlanComponent {
  readonly plan = input.required<RecoveryPlan>();
  readonly title = input("Today's childcare coverage");
  readonly badge = input('Current plan');
  readonly friendlyPerson = friendlyPerson;
  readonly money = Number;
}
