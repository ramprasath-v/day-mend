import { CurrencyPipe, DatePipe } from '@angular/common';
import { Component, computed, input, output } from '@angular/core';

import { RecoveryCase } from '../../core/recovery.models';
import { INITIAL_STATUS, RECOVERY_STATUS_COPY } from '../../core/recovery-status';

@Component({
  selector: 'app-recovery-hero',
  imports: [CurrencyPipe, DatePipe],
  templateUrl: './recovery-hero.html',
  styleUrl: './recovery-hero.css',
})
export class RecoveryHeroComponent {
  readonly recovery = input<RecoveryCase | null>(null);
  readonly busy = input(false);
  readonly resetDemo = output<void>();
  readonly money = Number;
  readonly status = computed(() => {
    const recovery = this.recovery();
    return recovery ? RECOVERY_STATUS_COPY[recovery.status] : INITIAL_STATUS;
  });
}
