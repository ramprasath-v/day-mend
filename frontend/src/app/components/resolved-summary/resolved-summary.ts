import { CurrencyPipe } from '@angular/common';
import { Component, input } from '@angular/core';

import { RecoveryCase } from '../../core/recovery.models';

@Component({
  selector: 'app-resolved-summary',
  imports: [CurrencyPipe],
  templateUrl: './resolved-summary.html',
  styleUrl: './resolved-summary.css',
})
export class ResolvedSummaryComponent {
  readonly recovery = input.required<RecoveryCase>();
  readonly money = Number;
  calendarCount(): number {
    return this.recovery().execution_actions.filter(
      (action) => action.action_type === 'UPDATE_CALENDAR',
    ).length;
  }
}
