import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { FamilyService, FamilyProfile, familyError } from '../core/family.service';

@Component({
  selector: 'app-settings',
  imports: [FormsModule],
  templateUrl: './settings.html',
  styleUrl: './family-editor.css',
})
export class SettingsPage {
  readonly api = inject(FamilyService);
  readonly profile = signal<FamilyProfile | null>(null);
  readonly saving = signal(false);
  readonly message = signal('');
  readonly error = signal('');
  constructor() { this.load(); }
  load() {
    this.error.set('');
    this.api.get().subscribe({
      next: profile => { profile.policy.automatic_spend_limit = Number(profile.policy.automatic_spend_limit).toFixed(2); this.profile.set(profile); this.message.set(''); },
      error: error => this.error.set(familyError(error)),
    });
  }
  save() {
    const profile = this.profile();
    if (!profile || this.saving()) return;
    this.error.set(''); this.message.set('');
    if (!/^\d{1,8}(\.\d{1,2})?$/.test(String(profile.policy.automatic_spend_limit))) {
      this.error.set('Enter a non-negative spending limit with no more than two decimal places.'); return;
    }
    this.saving.set(true);
    this.api.savePolicy(profile).subscribe({
      next: saved => { saved.policy.automatic_spend_limit = Number(saved.policy.automatic_spend_limit).toFixed(2); this.profile.set(saved); this.saving.set(false); this.message.set('Saved. These rules apply to your next recovery.'); },
      error: error => { this.saving.set(false); this.error.set(familyError(error)); },
    });
  }
}
