import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import {
  ApprovalDecisionRequest,
  CreateRecoveryRequest,
  ExternalEventRequest,
  RecoveryCase,
} from './recovery.models';

@Injectable({ providedIn: 'root' })
export class RecoveryApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = environment.apiBaseUrl;

  health(): Observable<{ status: 'ok'; service: string }> {
    return this.http.get<{ status: 'ok'; service: string }>(`${this.baseUrl}/health`);
  }

  startRecovery(request: CreateRecoveryRequest): Observable<RecoveryCase> {
    return this.http.post<RecoveryCase>(`${this.baseUrl}/recoveries`, request);
  }

  getRecovery(recoveryCaseId: string): Observable<RecoveryCase> {
    return this.http.get<RecoveryCase>(`${this.baseUrl}/recoveries/${recoveryCaseId}`);
  }

  submitEvent(recoveryCaseId: string, event: ExternalEventRequest): Observable<RecoveryCase> {
    return this.http.post<RecoveryCase>(
      `${this.baseUrl}/recoveries/${recoveryCaseId}/events`,
      event,
    );
  }

  decideApproval(
    recoveryCaseId: string,
    approvalId: string,
    decision: ApprovalDecisionRequest,
  ): Observable<RecoveryCase> {
    return this.http.post<RecoveryCase>(
      `${this.baseUrl}/recoveries/${recoveryCaseId}/approvals/${approvalId}`,
      decision,
    );
  }
}
