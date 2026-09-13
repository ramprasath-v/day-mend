import { TestBed, ComponentFixture } from '@angular/core/testing';
import { Type } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { FamilyPage } from './family';
import { SettingsPage } from './settings';
import { familyFixture } from '../testing/family.fixture';
import { environment } from '../../environments/environment';
import { ApprovalCardComponent } from '../components/approval-card/approval-card';
import { LiveRecoveryComponent } from '../components/live-recovery/live-recovery';
import { approvalCase, resolvedCase } from '../testing/recovery.fixture';

describe('Editable family and deterministic settings', () => {
  let http: HttpTestingController;
  const url = environment.apiBaseUrl + '/family';
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [FamilyPage, SettingsPage, ApprovalCardComponent, LiveRecoveryComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => http.verify());
  function open<T extends FamilyPage | SettingsPage>(type: Type<T>): ComponentFixture<T> {
    const fixture = TestBed.createComponent(type);
    http.expectOne(url).flush(structuredClone(familyFixture));
    fixture.detectChanges();
    return fixture;
  }
  it('renders retrieved caregiver facts and opens a lightweight editor', () => {
    const fixture = open(FamilyPage);
    expect(fixture.nativeElement.textContent).toContain('Family helper');
    expect(fixture.nativeElement.textContent).toContain('Helper home');
    const edit = [...fixture.nativeElement.querySelectorAll('button')].find((b: any) => b.textContent.includes('Edit Family helper')) as HTMLButtonElement;
    edit.click(); fixture.detectChanges();
    expect(fixture.nativeElement.querySelectorAll('input[type="datetime-local"]').length).toBe(2);
    expect(fixture.componentInstance.editing()).toBe('helper');
    expect(fixture.nativeElement.textContent).toContain('Save caregiver');
  });
  it('sends changed availability, location, transport and trust without protected caregiver fields', async () => {
    const fixture = open(FamilyPage);
    const page = fixture.componentInstance;
    page.edit('helper'); fixture.detectChanges();
    await fixture.whenStable();
    const checkboxes = fixture.nativeElement.querySelectorAll('.person input[type="checkbox"]');
    checkboxes[0].click(); checkboxes[1].click();
    const person = page.profile()!.caregivers[0];
    person.location_id = 'family_home';
    person.availability[0].start = '2026-08-27T17:00:00Z';
    page.save('facts');
    expect(page.saving()).toBeTrue();
    expect(page.message()).toBe('');
    const request = http.expectOne(url);
    expect(request.request.method).toBe('PUT');
    expect(request.request.body.expected_version).toBe(1);
    expect(request.request.body.caregivers[0]).toEqual(person);
    expect(person.can_transport_child).toBeFalse();
    expect(person.is_trusted).toBeFalse();
    expect(request.request.body.caregivers[0].hourly_rate).toBeUndefined();
    request.flush({ ...page.profile(), version: 2 });
    expect(page.message()).toContain('Saved.');
    expect(page.profile()!.version).toBe(2);
    expect(page.editing()).toBeNull();
  });
  it('blocks reversed availability without sending a save', () => {
    const fixture = open(FamilyPage);
    const page = fixture.componentInstance;
    page.profile()!.caregivers[0].availability[0].end = '2026-08-27T15:00:00Z';
    page.save('facts');
    expect(page.error()).toContain('Start must be before end');
    http.expectNone(url);
  });
  it('blocks overlapping availability', () => {
    const page = open(FamilyPage).componentInstance;
    const windows = page.profile()!.caregivers[0].availability;
    windows.push({ ...windows[0] });
    page.save('facts');
    expect(page.error()).toContain('non-overlapping');
    http.expectNone(url);
  });
  it('saves all soft preferences through the separate endpoint', () => {
    const fixture = open(FamilyPage);
    const page = fixture.componentInstance;
    const preferences = page.profile()!.preferences;
    preferences.prefer_trusted_caregivers = true; preferences.prefer_in_home_care = true;
    preferences.prefer_fewer_handoffs = false; preferences.protect_critical_meetings = true;
    page.save('preferences');
    const request = http.expectOne(url + '/preferences');
    expect(request.request.body).toEqual({ expected_version: 1, prefer_trusted_caregivers: true,
      prefer_in_home_care: true, minimize_handoffs: false, protect_critical_meetings: true });
    request.flush({ ...page.profile(), version: 2 });
    expect(page.message()).toContain('Saved.');
  });
  it('preserves caregiver edits after a failed save and never shows success', () => {
    const page = open(FamilyPage).componentInstance;
    page.profile()!.caregivers[0].name = 'Edited helper';
    page.save('facts');
    http.expectOne(url).flush({ detail: 'Could not save' }, { status: 500, statusText: 'Failure' });
    expect(page.error()).toContain('not been confirmed');
    expect(page.message()).toBe('');
    expect(page.profile()!.caregivers[0].name).toBe('Edited helper');
    expect(page.saving()).toBeFalse();
  });
  it('shows version-conflict feedback without retrying or overwriting', () => {
    const page = open(FamilyPage).componentInstance;
    page.save('facts');
    http.expectOne(url).flush({}, { status: 409, statusText: 'Conflict' });
    expect(page.error()).toContain('changed elsewhere');
    expect(page.message()).toBe('');
  });
  it('shows a load failure rather than a fabricated default', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    http.expectOne(url).flush({}, { status: 503, statusText: 'Unavailable' });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('input')).toBeNull();
    expect(fixture.nativeElement.querySelector('[role="alert"]')).not.toBeNull();
  });
  it('renders exact cents and saves all hard policy settings and notification mode', async () => {
    const fixture = open(SettingsPage);
    await fixture.whenStable();
    expect(fixture.nativeElement.querySelector('input[inputmode="decimal"]').value).toBe('30.00');
    const page = fixture.componentInstance;
    page.profile()!.policy.automatic_spend_limit = '87.75';
    const toggles = fixture.nativeElement.querySelectorAll('input[type="checkbox"]');
    toggles.forEach((toggle: HTMLInputElement) => toggle.click());
    page.profile()!.notification_mode = 'completion_only';
    page.save();
    const request = http.expectOne(url + '/policy');
    expect(request.request.body).toEqual({
      expected_version: 1, automatic_spend_limit: '87.75',
      require_approval_for_unfamiliar_provider: false,
      allow_external_backup_providers: false, allow_provider_transport: false,
      notification_mode: 'completion_only',
    });
    expect(page.message()).toBe('');
    request.flush({ ...page.profile(), version: 2 });
    fixture.detectChanges();
    await fixture.whenStable();
    expect(fixture.nativeElement.querySelector('input[inputmode="decimal"]').value).toBe('87.75');
    expect(page.message()).toContain('Saved.');
  });
  for (const amount of ['-1', '1.001', '', 'NaN', '100000000']) {
    it('rejects invalid spending value ' + amount, () => {
      const page = open(SettingsPage).componentInstance;
      page.profile()!.policy.automatic_spend_limit = amount;
      page.save();
      expect(page.error()).toContain('two decimal places');
      http.expectNone(url + '/policy');
    });
  }
  it('keeps settings edits and shows no success after an API failure', () => {
    const page = open(SettingsPage).componentInstance;
    page.profile()!.policy.automatic_spend_limit = '42.50';
    page.save();
    http.expectOne(url + '/policy').flush({}, { status: 500, statusText: 'Failure' });
    expect(page.profile()!.policy.automatic_spend_limit).toBe('42.50');
    expect(page.message()).toBe('');
    expect(page.error()).not.toBe('');
  });
  it('prevents duplicate settings saves while one request is pending', () => {
    const page = open(SettingsPage).componentInstance;
    page.save(); page.save();
    const requests = http.match(url + '/policy');
    expect(requests.length).toBe(1);
    requests[0].flush({ ...page.profile(), version: 2 });
  });
  it('shows both spending and unfamiliar-provider reasons from the recovery snapshot', () => {
    const fixture = TestBed.createComponent(ApprovalCardComponent);
    fixture.componentRef.setInput('recovery', { ...approvalCase, automatic_spend_limit: '40.50',
      pending_approval: { ...approvalCase.pending_approval!, amount: '87.75', reason: 'The valid plan exceeds the limit and uses an unfamiliar paid caregiver.' } });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Above your $40.5 automatic-spend limit.');
    expect(fixture.nativeElement.textContent).toContain('unfamiliar paid caregiver');
    expect(fixture.nativeElement.textContent).toContain('Approve $87.75');
    fixture.componentRef.setInput('recovery', { ...approvalCase, automatic_spend_limit: '100',
      pending_approval: { ...approvalCase.pending_approval!, amount: '87.75', reason: 'Unfamiliar provider requires approval.' } });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).not.toContain('Above your');
    expect(fixture.nativeElement.textContent).toContain('Unfamiliar provider requires approval.');
  });
  for (const mode of ['decisions_only', 'completion_only', 'meaningful_changes'] as const) {
    it('keeps approval and the full journal available for ' + mode, () => {
      const fixture = TestBed.createComponent(LiveRecoveryComponent);
      fixture.componentRef.setInput('recovery', { ...approvalCase, notification_mode: mode });
      fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('Awaiting approval');
      expect(fixture.nativeElement.querySelector('details')).not.toBeNull();
      expect(fixture.componentInstance.showActivitySummary()).toBe(mode === 'meaningful_changes');
      fixture.componentRef.setInput('recovery', { ...resolvedCase, notification_mode: mode });
      fixture.detectChanges();
      expect(fixture.componentInstance.showStatusSummary()).toBe(mode !== 'decisions_only');
    });
  }
});
