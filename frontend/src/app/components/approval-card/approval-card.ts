import { CurrencyPipe, DatePipe } from '@angular/common';
import { Component, computed, input, output } from '@angular/core';

import { friendlyPerson } from '../../core/recovery-status';
import { RecoveryCase } from '../../core/recovery.models';

@Component({
  selector: 'app-approval-card',
  imports: [CurrencyPipe, DatePipe],
  templateUrl: './approval-card.html',
  styleUrl: './approval-card.css',
})
export class ApprovalCardComponent {
  readonly recovery = input.required<RecoveryCase>();
  readonly busy = input(false);
  readonly approve = output<void>();
  readonly reject = output<void>();
  readonly money = Number;
  readonly friendlyPerson = friendlyPerson;
  readonly paidCare = computed(() => this.recovery().active_plan?.coverage_segments.filter(segment => segment.segment_type !== 'TRANSPORT' && Number(segment.estimated_cost) > 0) ?? []);
}
