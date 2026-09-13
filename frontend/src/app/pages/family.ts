import { Component, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { FamilyService, FamilyProfile, familyError, localDateTime, toInstant, validWindow } from '../core/family.service';
import { CoverageWindow } from '../core/recovery.models';

@Component({
  selector: 'app-family',
  imports: [DatePipe, FormsModule],
  templateUrl: './family.html',
  styleUrl: './family-editor.css',
})
export class FamilyPage {
  readonly api = inject(FamilyService);
  readonly profile = signal<FamilyProfile | null>(null);
  readonly saving = signal(false);
  readonly message = signal('');
  readonly error = signal('');
  readonly editing = signal<string | null>(null);
  readonly localDateTime = localDateTime;
  readonly timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  private saved: FamilyProfile | null = null;
  constructor() { this.load(); }
  load() {
    this.error.set('');
    this.api.get().subscribe({
      next: profile => { this.saved = structuredClone(profile); this.profile.set(profile); this.editing.set(null); this.message.set(''); },
      error: error => this.error.set(familyError(error)),
    });
  }
  edit(id: string) { this.editing.set(id); this.message.set(''); this.error.set(''); }
  cancel() {
    if (this.saved) this.profile.set(structuredClone(this.saved));
    this.editing.set(null); this.error.set('');
  }
  setTime(window: CoverageWindow, field: 'start' | 'end', value: string) { window[field] = toInstant(value); }
  save(section: 'facts' | 'preferences') {
    const profile = this.profile();
    if (!profile || this.saving()) return;
    this.message.set(''); this.error.set('');
    if (section === 'facts' && (!validWindow(profile.required_care_schedule) || profile.caregivers.some(c =>
      !c.name.trim() || !c.relationship.trim() || !c.location_id || c.availability.some(w => !validWindow(w))
      || [...c.availability].sort((a,b) => Date.parse(a.start)-Date.parse(b.start)).some((w,i,all) => i > 0 && Date.parse(all[i-1].end) > Date.parse(w.start))))) {
      this.error.set('Enter a name, relationship, known location and valid, non-overlapping availability windows. Start must be before end.');
      return;
    }
    this.saving.set(true);
    const request = section === 'facts' ? this.api.saveFamily(profile) : this.api.savePreferences(profile);
    request.subscribe({
      next: saved => { this.saved = structuredClone(saved); this.profile.set(saved); this.saving.set(false); this.editing.set(null); this.message.set('Saved. These changes apply to your next recovery.'); },
      error: error => { this.saving.set(false); this.error.set(familyError(error)); },
    });
  }
}
