import { Component, input, output } from '@angular/core';

import { RecoveryCase } from '../../core/recovery.models';

@Component({
  selector: 'app-demo-controls',
  templateUrl: './demo-controls.html',
  styleUrl: './demo-controls.css',
})
export class DemoControlsComponent {
  readonly recovery = input<RecoveryCase | null>(null);
  readonly busy = input(false);
  readonly start = output<void>();
  readonly decline = output<void>();
  readonly refresh = output<void>();
  canDecline(): boolean {
    const recovery = this.recovery();
    return (
      !!recovery &&
      recovery.status === 'WAITING_FOR_RESPONSE' &&
      !recovery.events.some((event) => event.event_type === 'CAREGIVER_DECLINED')
    );
  }
}
