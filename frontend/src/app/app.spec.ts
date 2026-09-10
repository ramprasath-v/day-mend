import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';

import { environment } from '../environments/environment';
import { App } from './app';
import {
  ProgressEventHandler,
  RecoveryProgressService,
} from './core/recovery-progress.service';
import { RecoveryProgressEvent } from './core/recovery.models';
import { RECOVERY_STATUS_COPY } from './core/recovery-status';
import { approvalCase, planACase, rejectedCase, resolvedCase } from './testing/recovery.fixture';

class FakeRecoveryProgressService {
  handler: ProgressEventHandler | null = null;
  connectionHandler: ((connected: boolean) => void) | null = null;

  connect(
    _progressId: string,
    onEvent: ProgressEventHandler,
    onConnectionChange?: (connected: boolean) => void,
  ): () => void {
    this.handler = onEvent;
    this.connectionHandler = onConnectionChange ?? null;
    onConnectionChange?.(true);
    return () => {
      this.handler = null;
      this.connectionHandler = null;
    };
  }

  emit(event: RecoveryProgressEvent): void {
    this.handler?.(event);
  }

  setConnected(connected: boolean): void {
    this.connectionHandler?.(connected);
  }
}

describe('DayMend recovery experience', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    localStorage.clear();
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: RecoveryProgressService, useClass: FakeRecoveryProgressService },
      ],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http
      .match((request) => request.url.includes('/progress/'))
      .forEach((request) => request.flush([]));
    http.verify();
  });

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
    expect(text(fixture)).toContain('DayMend is rebuilding today’s plan');
    const request = http.expectOne(`${environment.apiBaseUrl}/recoveries`);
    expect(request.request.method).toBe('POST');
    expect(request.request.body.caregiver_id).toBe('nanny');
    request.flush(planACase);
    fixture.detectChanges();
  }

  it('loads a status-based normal-day experience with no chat input', () => {
    const fixture = create();
    expect(text(fixture)).toContain('Your day is covered');
    expect(text(fixture)).toContain('Nanny unavailable');
    expect(fixture.debugElement.query(By.css('input'))).toBeNull();
    expect(fixture.debugElement.query(By.css('textarea'))).toBeNull();
  });

  it('shows a prominent neutral working state while recovery is pending', () => {
    const fixture = create();
    fixture.debugElement.query(By.css('app-demo-controls .button--primary')).nativeElement.click();
    fixture.detectChanges();

    expect(text(fixture)).toContain('DayMend is rebuilding today’s plan');
    expect(text(fixture)).toContain('Understanding the change');
    expect(text(fixture)).toContain('Building your plan');
    expect(text(fixture)).toContain('Checking every detail');
    expect(text(fixture)).toContain('Your decision');
    expect(text(fixture)).toContain('Connecting to DayMend');
    expect(fixture.debugElement.query(By.css('app-demo-controls'))).toBeNull();

    http.expectOne(`${environment.apiBaseUrl}/recoveries`).flush(planACase);
  });

  it('renders real ordered progress and safe validation detail while a request runs', () => {
    const fixture = create();
    fixture.debugElement.query(By.css('app-demo-controls .button--primary')).nativeElement.click();
    const progress = TestBed.inject(
      RecoveryProgressService,
    ) as unknown as FakeRecoveryProgressService;
    const validationEvent: RecoveryProgressEvent = {
      id: 'progress:1',
      progress_id: 'progress',
      recovery_case_id: null,
      sequence: 1,
      timestamp: '2026-09-08T12:00:00Z',
      event_type: 'VALIDATION_FAILED',
      actor_type: 'DETERMINISTIC_SERVICE',
      actor_name: 'plan_validator',
      stage: 'PLAN_A',
      status: 'WARNING',
      summary: 'Plan needs deterministic repair',
      details: { attempt_number: 1, issue_count: 1, issue_codes: ['coverage_gap'] },
    };
    progress.emit(validationEvent);
    progress.emit(validationEvent);
    progress.setConnected(false);
    fixture.detectChanges();

    expect(text(fixture)).toContain('Plan needs deterministic repair');
    expect(text(fixture)).toContain('Attempt 1');
    expect(text(fixture)).toContain('1 validation issue');
    expect(text(fixture)).toContain('coverage_gap');
    expect(text(fixture)).toContain('WARNING');
    expect(text(fixture)).toContain('Connecting');
    expect(fixture.debugElement.queryAll(By.css('.event-feed li')).length).toBe(1);
    expect(
      fixture.debugElement.queryAll(By.css('.orchestration__node--warning')).length,
    ).toBe(1);

    http.expectOne(`${environment.apiBaseUrl}/recoveries`).flush(planACase);
  });

  it('distinguishes repair, research, and human approval stages from real events', () => {
    const fixture = create();
    fixture.debugElement.query(By.css('app-demo-controls .button--primary')).nativeElement.click();
    const progress = TestBed.inject(
      RecoveryProgressService,
    ) as unknown as FakeRecoveryProgressService;
    const base: Omit<RecoveryProgressEvent, 'id' | 'sequence' | 'event_type' | 'actor_type' | 'actor_name' | 'status' | 'summary'> = {
      progress_id: 'progress',
      recovery_case_id: 'case-ui-demo',
      timestamp: '2026-09-08T12:00:00Z',
      stage: 'PLAN_B',
      details: {},
    };
    progress.emit({
      ...base,
      id: 'progress:repair',
      sequence: 1,
      event_type: 'PLAN_REPAIR_STARTED',
      actor_type: 'AGENT',
      actor_name: 'constraint_planner',
      status: 'ACTIVE',
      summary: 'Repairing every listed validation issue',
      details: { attempt_number: 2 },
    });
    progress.emit({
      ...base,
      id: 'progress:research',
      sequence: 2,
      event_type: 'BACKUP_SELECTED',
      actor_type: 'AGENT',
      actor_name: 'backup_care_research',
      status: 'COMPLETED',
      summary: 'Grounded replacement recommended',
      details: { recommended_candidate_id: 'harbor_nanny_coop' },
    });
    progress.emit({
      ...base,
      id: 'progress:approval',
      sequence: 3,
      event_type: 'APPROVAL_REQUIRED',
      actor_type: 'HUMAN',
      actor_name: 'user',
      status: 'WARNING',
      summary: 'Human approval required before execution',
      details: { cost: '92' },
    });
    fixture.detectChanges();

    expect(text(fixture)).toContain('Repairing every listed validation issue');
    expect(text(fixture)).toContain('Grounded replacement recommended');
    expect(text(fixture)).toContain('Harbor Nanny Coop');
    expect(text(fixture)).toContain('Human approval required before execution');
    expect(fixture.debugElement.queryAll(By.css('.orchestration__node--active')).length).toBe(1);

    http.expectOne(`${environment.apiBaseUrl}/recoveries`).flush(planACase);
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
    expect(text(fixture)).toContain('DayMend is rebuilding today’s plan');
    const request = http.expectOne(`${environment.apiBaseUrl}/recoveries/case-ui-demo/events`);
    expect(request.request.body.event_type).toBe('CAREGIVER_DECLINED');
    expect(request.request.body.expected_version).toBe(1);
    request.flush(approvalCase);
    fixture.detectChanges();
    expect(text(fixture)).toContain('Recovery Plan B');
    expect(text(fixture)).toContain('Grandma is no longer available');
    expect(text(fixture)).toContain('Plan A segments still worked');
    expect(text(fixture)).toContain('Preserved');
    expect(text(fixture)).toContain('Invalidated');
    expect(text(fixture)).toContain('Replacement');
    expect(text(fixture)).toContain('Your approval is needed');
    expect(text(fixture)).toContain('Automatic-spend limit');
    expect(text(fixture)).toContain('$30');
    expect(text(fixture)).toContain('Approve $92');
    const pageText = text(fixture);
    expect(pageText.indexOf('What changed')).toBeLessThan(pageText.indexOf('Recovery Plan B'));
  });

  it('elevates a new Plan B caregiver using only plan and assumption data', () => {
    const fixture = create();
    startAndFlush(fixture);
    fixture.debugElement
      .query(By.css('app-demo-controls .button--secondary'))
      .nativeElement.click();
    const priorPlan = approvalCase.previous_plans[0];
    const researchedCase = {
      ...approvalCase,
      active_plan: {
        ...approvalCase.active_plan!,
        estimated_cost: '116',
        coverage_segments: [
          priorPlan.coverage_segments[0],
          priorPlan.coverage_segments[1],
          {
            segment_id: 'harbor-replacement',
            window: {
              start: '2026-08-27T10:00:00-07:00',
              end: '2026-08-27T13:00:00-07:00',
            },
            assigned_person_id: 'harbor_nanny_coop',
            source: 'CAREGIVER' as const,
            segment_type: 'CARE' as const,
            location_id: 'family_home',
            location_label: 'Family home',
            estimated_cost: '72',
          },
          priorPlan.coverage_segments[3],
          priorPlan.coverage_segments[4],
        ],
      },
    };
    http
      .expectOne(`${environment.apiBaseUrl}/recoveries/case-ui-demo/events`)
      .flush(researchedCase);
    fixture.detectChanges();

    expect(text(fixture)).toContain('Backup care recommendation');
    expect(text(fixture)).toContain('Harbor Nanny Coop');
    expect(text(fixture)).toContain('In-home care · Family home');
    expect(text(fixture)).toContain('Covers the affected window');
    expect(text(fixture)).toContain('Every minute checked');
    expect(text(fixture)).not.toContain('rating');
    expect(text(fixture)).not.toContain('review');
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
    const progress = TestBed.inject(
      RecoveryProgressService,
    ) as unknown as FakeRecoveryProgressService;
    progress.emit({
      id: 'progress:execution',
      progress_id: 'progress',
      recovery_case_id: 'case-ui-demo',
      sequence: 10,
      timestamp: '2026-09-08T12:00:00Z',
      event_type: 'ACTION_SUCCEEDED',
      actor_type: 'DETERMINISTIC_SERVICE',
      actor_name: 'execution_service',
      stage: 'RECOVERY',
      status: 'COMPLETED',
      summary: 'Recovery action completed',
      details: { action_type: 'RESERVE_CAREGIVER', success: true },
    });
    progress.emit({
      id: 'progress:completion',
      progress_id: 'progress',
      recovery_case_id: 'case-ui-demo',
      sequence: 11,
      timestamp: '2026-09-08T12:00:01Z',
      event_type: 'COMPLETION_VERIFIED',
      actor_type: 'DETERMINISTIC_SERVICE',
      actor_name: 'completion_verifier',
      stage: 'RECOVERY',
      status: 'COMPLETED',
      summary: 'Final childcare coverage verified',
      details: { success: true },
    });
    const request = http.expectOne(
      `${environment.apiBaseUrl}/recoveries/case-ui-demo/approvals/approval-1`,
    );
    expect(request.request.body).toEqual({ decision: 'APPROVE', expected_version: 3 });
    request.flush(resolvedCase);
    fixture.detectChanges();
    expect(text(fixture)).toContain('Day recovered');
    expect(text(fixture)).toContain('Childcare coverage restored through 4:00 PM');
    expect(text(fixture)).toContain('Recovery action completed');
    expect(text(fixture)).toContain('Final childcare coverage verified');
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
    request.flush(rejectedCase);
    fixture.detectChanges();
    expect(text(fixture)).toContain('DayMend is looking for another option');
    expect(text(fixture)).toContain('Recovery not approved');
    expect(text(fixture)).toContain('No recovery actions were taken');
    expect(text(fixture)).toContain('Plan B not approved');
    expect(text(fixture)).not.toContain('Day recovered');
    expect(text(fixture)).not.toContain('Simulated execution');
    expect(text(fixture)).not.toContain('Deterministic verifier');
    expect(text(fixture)).not.toContain('Plan C');
  });

  it('does not render success when a reject request receives an inconsistent resolved case', () => {
    const fixture = create();
    startAndFlush(fixture);
    fixture.debugElement
      .query(By.css('app-demo-controls .button--secondary'))
      .nativeElement.click();
    http.expectOne(`${environment.apiBaseUrl}/recoveries/case-ui-demo/events`).flush(approvalCase);
    fixture.detectChanges();
    fixture.debugElement.query(By.css('app-approval-card .button--quiet')).nativeElement.click();
    http
      .expectOne(`${environment.apiBaseUrl}/recoveries/case-ui-demo/approvals/approval-1`)
      .flush(resolvedCase);
    fixture.detectChanges();

    expect(text(fixture)).toContain('inconsistent approval result');
    expect(text(fixture)).toContain('Your approval is needed');
    expect(text(fixture)).not.toContain('Day recovered');
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
    expect(RECOVERY_STATUS_COPY.DETECTED.eyebrow).toBe('Childcare changed');
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

  it('resets the local demo without calling a backend reset endpoint', () => {
    const fixture = create();
    startAndFlush(fixture);

    fixture.debugElement
      .query(By.css('app-recovery-hero .button--secondary'))
      .nativeElement.click();
    fixture.detectChanges();

    expect(localStorage.getItem('daymend.recoveryCaseId')).toBeNull();
    expect(text(fixture)).toContain('Nanny unavailable');
  });

  it('shows the current architecture only inside compact technical details', () => {
    const fixture = create();

    expect(text(fixture)).toContain('AgentCore · 3 Strands agents · Claude Sonnet 4.5');
    expect(text(fixture)).toContain('How DayMend works');
    expect(text(fixture)).not.toContain('One recovery agent');
    expect(text(fixture)).not.toContain('Amazon Nova Pro');
  });
});
