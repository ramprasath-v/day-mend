import { CurrencyPipe } from '@angular/common';
import { Component, input, output } from '@angular/core';

import { RecoveryCase } from '../../core/recovery.models';

@Component({
  selector: 'app-approval-card',
  imports: [CurrencyPipe],
  templateUrl: './approval-card.html',
  styleUrl: './approval-card.css',
})
export class ApprovalCardComponent {
  readonly recovery = input.required<RecoveryCase>();
  readonly busy = input(false);
  readonly approve = output<void>();
  readonly reject = output<void>();
  readonly money = Number;
}
