import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';

import { environment } from '../environments/environment';
import { App } from './app';
import { RECOVERY_STATUS_COPY } from './core/recovery-status';
import { approvalCase, planACase, resolvedCase } from './testing/recovery.fixture';

describe('DayMend recovery experience', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    localStorage.clear();
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  function create() {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    return fixture;
  }

  function text(fixture: ReturnType<typeof create>): string {
    return fixture.nativeElement.textContent.replace(/\s+/g, ' ').trim();
  }

  function startAndFlush(fixture: ReturnType<typeof create>): void {
    const start = fixture.debugElement.query(By.css('app-demo-controls .button--primary'));
    start.nativeElement.click();
    fixture.detectChanges();
    expect(start.nativeElement.disabled).toBeTrue();
    const request = http.expectOne(`${environment.apiBaseUrl}/recoveries`);
    expect(request.request.method).toBe('POST');
    expect(request.request.body.caregiver_id).toBe('nanny');
    request.flush(planACase);
    fixture.detectChanges();
  }

  it('loads a status-based normal-day experience with no chat input', () => {
    const fixture = create();
    expect(text(fixture)).toContain('Your day is covered');
    expect(text(fixture)).toContain('Simulate nanny cancellation');
    expect(fixture.debugElement.query(By.css('input'))).toBeNull();
    expect(fixture.debugElement.query(By.css('textarea'))).toBeNull();
  });

  it('starts recovery, renders friendly status, plan segments, and cost', () => {
    const fixture = create();
    startAndFlush(fixture);
    expect(text(fixture)).toContain('Your day has a workable Plan A');
    expect(text(fixture)).toContain('Employer backup care');
    expect(text(fixture)).toContain('Backup sitter');
    expect(text(fixture)).toContain('$92');
    expect(text(fixture)).not.toContain('employer_backup_care');
  });

  it('submits Grandma decline and renders Plan B, impact, and approval boundary', () => {
    const fixture = create();
    startAndFlush(fixture);
    const decline = fixture.debugElement.query(By.css('app-demo-controls .button--secondary'));
    decline.nativeElement.click();
    fixture.detectChanges();
    expect(decline.nativeElement.disabled).toBeTrue();
    const request = http.expectOne(`${environment.apiBaseUrl}/recoveries/case-ui-demo/events`);
    expect(request.request.body.event_type).toBe('CAREGIVER_DECLINED');
    expect(request.request.body.expected_version).toBe(1);
    request.flush(approvalCase);
    fixture.detectChanges();
    expect(text(fixture)).toContain('Recovery Plan B');
    expect(text(fixture)).toContain('Grandma is no longer available');
    expect(text(fixture)).toContain('Plan A segments still worked');
    expect(text(fixture)).toContain('Your approval is needed');
    expect(text(fixture)).toContain('Automatic-spend limit');
    expect(text(fixture)).toContain('$30');
    expect(text(fixture)).toContain('Approve $92');
  });

  it('approves the current request and renders backend-confirmed resolution', () => {
    const fixture = create();
    startAndFlush(fixture);
    fixture.debugElement
      .query(By.css('app-demo-controls .button--secondary'))
      .nativeElement.click();
    http.expectOne(`${environment.apiBaseUrl}/recoveries/case-ui-demo/events`).flush(approvalCase);
    fixture.detectChanges();
    fixture.debugElement.query(By.css('app-approval-card .button--primary')).nativeElement.click();
    const request = http.expectOne(
      `${environment.apiBaseUrl}/recoveries/case-ui-demo/approvals/approval-1`,
    );
    expect(request.request.body).toEqual({ decision: 'APPROVE', expected_version: 3 });
    request.flush(resolvedCase);
    fixture.detectChanges();
    expect(text(fixture)).toContain('Day recovered');
    expect(text(fixture)).toContain('Your day is covered through 4:00 PM');
    expect(text(fixture)).toContain('Backup coverage');
    expect(text(fixture)).toContain('Confirmed');
    expect(text(fixture)).toContain('Final verification');
    expect(text(fixture)).toContain('Passed');
  });

  it('rejects without inventing an alternate plan', () => {
    const fixture = create();
    startAndFlush(fixture);
    fixture.debugElement
      .query(By.css('app-demo-controls .button--secondary'))
      .nativeElement.click();
    http.expectOne(`${environment.apiBaseUrl}/recoveries/case-ui-demo/events`).flush(approvalCase);
    fixture.detectChanges();
    fixture.debugElement.query(By.css('app-approval-card .button--quiet')).nativeElement.click();
    const request = http.expectOne(
      `${environment.apiBaseUrl}/recoveries/case-ui-demo/approvals/approval-1`,
    );
    expect(request.request.body).toEqual({
      decision: 'REJECT',
      expected_version: 3,
      reason: 'Parent declined recovery cost',
    });
    request.flush({ ...approvalCase, status: 'REPLANNING', pending_approval: null });
    fixture.detectChanges();
    expect(text(fixture)).toContain('DayMend is looking for another option');
    expect(text(fixture)).not.toContain('Plan C');
  });

  it('shows a safe error message without backend details', () => {
    const fixture = create();
    fixture.debugElement.query(By.css('app-demo-controls .button--primary')).nativeElement.click();
    http
      .expectOne(`${environment.apiBaseUrl}/recoveries`)
      .flush(
        { error: { code: 'PLANNING_FAILED', message: 'internal model details' } },
        { status: 409, statusText: 'Conflict' },
      );
    fixture.detectChanges();
    expect(text(fixture)).toContain("DayMend couldn't complete this recovery plan.");
    expect(text(fixture)).not.toContain('internal model details');
  });

  it('maps every backend status to parent-friendly copy', () => {
    expect(RECOVERY_STATUS_COPY.DETECTED.eyebrow).toBe('Childcare disruption detected');
    expect(RECOVERY_STATUS_COPY.REPLANNING.title).toContain('another option');
    expect(RECOVERY_STATUS_COPY.APPROVAL_REQUIRED.title).toContain('valid recovery plan');
    expect(RECOVERY_STATUS_COPY.RESOLVED.title).toBe('Day recovered');
    expect(RECOVERY_STATUS_COPY.FAILED.title).not.toContain('FAILED');
  });

  it('restores the persisted recovery case after a page reload', () => {
    localStorage.setItem('daymend.recoveryCaseId', 'case-ui-demo');
    const fixture = create();
    const request = http.expectOne(`${environment.apiBaseUrl}/recoveries/case-ui-demo`);
    expect(request.request.method).toBe('GET');
    request.flush(resolvedCase);
    fixture.detectChanges();
    expect(text(fixture)).toContain('Day recovered');
  });
});
