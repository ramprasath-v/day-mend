import { HttpClient, HttpHeaders } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import {
  ApprovalDecisionRequest,
  CreateRecoveryRequest,
  ExternalEventRequest,
  RecoveryCase,
  RecoveryProgressEvent,
} from './recovery.models';

@Injectable({ providedIn: 'root' })
export class RecoveryApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = environment.apiBaseUrl;

  health(): Observable<{ status: 'ok'; service: string }> {
    return this.http.get<{ status: 'ok'; service: string }>(`${this.baseUrl}/health`);
  }

  startRecovery(request: CreateRecoveryRequest, progressId?: string): Observable<RecoveryCase> {
    return this.http.post<RecoveryCase>(`${this.baseUrl}/recoveries`, request, {
      headers: this.progressHeaders(progressId),
    });
  }

  getRecovery(recoveryCaseId: string): Observable<RecoveryCase> {
    return this.http.get<RecoveryCase>(`${this.baseUrl}/recoveries/${recoveryCaseId}`);
  }

  submitEvent(
    recoveryCaseId: string,
    event: ExternalEventRequest,
    progressId?: string,
  ): Observable<RecoveryCase> {
    return this.http.post<RecoveryCase>(
      `${this.baseUrl}/recoveries/${recoveryCaseId}/events`,
      event,
      { headers: this.progressHeaders(progressId) },
    );
  }

  decideApproval(
    recoveryCaseId: string,
    approvalId: string,
    decision: ApprovalDecisionRequest,
    progressId?: string,
  ): Observable<RecoveryCase> {
    return this.http.post<RecoveryCase>(
      `${this.baseUrl}/recoveries/${recoveryCaseId}/approvals/${approvalId}`,
      decision,
      { headers: this.progressHeaders(progressId) },
    );
  }

  getProgress(progressId: string): Observable<RecoveryProgressEvent[]> {
    return this.http.get<RecoveryProgressEvent[]>(
      `${this.baseUrl}/progress/${encodeURIComponent(progressId)}`,
    );
  }

  private progressHeaders(progressId?: string): HttpHeaders {
    return progressId
      ? new HttpHeaders({ 'X-DayMend-Progress-ID': progressId })
      : new HttpHeaders();
  }
}
