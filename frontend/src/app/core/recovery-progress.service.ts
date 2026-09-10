import { inject, Injectable, NgZone } from '@angular/core';

import { environment } from '../../environments/environment';
import { RecoveryProgressEvent } from './recovery.models';

export type ProgressEventHandler = (event: RecoveryProgressEvent) => void;

@Injectable({ providedIn: 'root' })
export class RecoveryProgressService {
  private readonly zone = inject(NgZone);
  private readonly baseUrl = environment.apiBaseUrl;

  connect(
    progressId: string,
    onEvent: ProgressEventHandler,
    onConnectionChange?: (connected: boolean) => void,
  ): () => void {
    const url = `${this.baseUrl}/progress/${encodeURIComponent(progressId)}/stream`;
    const source = new EventSource(url);

    source.onopen = () => this.zone.run(() => onConnectionChange?.(true));
    source.addEventListener('progress', (message) => {
      try {
        const event = JSON.parse((message as MessageEvent<string>).data) as RecoveryProgressEvent;
        this.zone.run(() => onEvent(event));
      } catch {
        // Ignore malformed transport data; the canonical snapshot remains available via HTTP.
      }
    });
    source.onerror = () => this.zone.run(() => onConnectionChange?.(false));

    return () => source.close();
  }
}
