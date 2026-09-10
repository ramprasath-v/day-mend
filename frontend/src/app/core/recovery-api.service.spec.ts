import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { environment } from '../../environments/environment';
import { approvalCase, planACase } from '../testing/recovery.fixture';
import { RecoveryApiService } from './recovery-api.service';

describe('RecoveryApiService', () => {
  let service: RecoveryApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(RecoveryApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('checks health and gets an existing recovery', () => {
    service.health().subscribe((result) => expect(result.status).toBe('ok'));
    http
      .expectOne(`${environment.apiBaseUrl}/health`)
      .flush({ status: 'ok', service: 'daymend-api' });

    service
      .getRecovery('case-ui-demo')
      .subscribe((result) => expect(result.status).toBe('WAITING_FOR_RESPONSE'));
    http.expectOne(`${environment.apiBaseUrl}/recoveries/case-ui-demo`).flush(planACase);
  });

  it('posts external events and approval decisions to case-scoped endpoints', () => {
    service
      .submitEvent('case-ui-demo', {
        event_type: 'CAREGIVER_DECLINED',
        caregiver_id: 'grandma',
        occurred_at: '2026-08-27T09:05:00-07:00',
        relevant_window: { start: '2026-08-27T10:00:00-07:00', end: '2026-08-27T13:00:00-07:00' },
        message: 'Unable to help',
        expected_version: 1,
      })
      .subscribe();
    const event = http.expectOne(`${environment.apiBaseUrl}/recoveries/case-ui-demo/events`);
    expect(event.request.method).toBe('POST');
    event.flush(approvalCase);

    service
      .decideApproval('case-ui-demo', 'approval-1', { decision: 'APPROVE', expected_version: 3 })
      .subscribe();
    const approval = http.expectOne(
      `${environment.apiBaseUrl}/recoveries/case-ui-demo/approvals/approval-1`,
    );
    expect(approval.request.method).toBe('POST');
    expect(approval.request.body).toEqual({ decision: 'APPROVE', expected_version: 3 });
    approval.flush(approvalCase);

    service
      .decideApproval('case-ui-demo', 'approval-1', {
        decision: 'REJECT',
        reason: 'Parent declined recovery cost',
        expected_version: 3,
      })
      .subscribe();
    const rejection = http.expectOne(
      `${environment.apiBaseUrl}/recoveries/case-ui-demo/approvals/approval-1`,
    );
    expect(rejection.request.method).toBe('POST');
    expect(rejection.request.body).toEqual({
      decision: 'REJECT',
      reason: 'Parent declined recovery cost',
      expected_version: 3,
    });
    rejection.flush(approvalCase);
  });

  it('correlates mutations to a resumable progress channel and reads its snapshot', () => {
    service
      .startRecovery(
        {
          disruption_type: 'CHILDCARE_UNAVAILABLE',
          occurred_at: '2026-08-27T07:02:00-07:00',
          caregiver_id: 'nanny',
          message: 'Unable to work',
        },
        'progress-ui-0001',
      )
      .subscribe();
    const start = http.expectOne(`${environment.apiBaseUrl}/recoveries`);
    expect(start.request.headers.get('X-DayMend-Progress-ID')).toBe('progress-ui-0001');
    start.flush(planACase);

    service.getProgress('progress-ui-0001').subscribe((events) => expect(events).toEqual([]));
    const snapshot = http.expectOne(`${environment.apiBaseUrl}/progress/progress-ui-0001`);
    expect(snapshot.request.method).toBe('GET');
    snapshot.flush([]);
  });
});
