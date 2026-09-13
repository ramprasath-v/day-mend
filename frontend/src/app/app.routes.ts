import { Routes } from '@angular/router';
import { TodayPage } from './pages/today';
import { HistoryPage } from './pages/history';
import { FamilyPage } from './pages/family';
import { SettingsPage } from './pages/settings';

export const routes: Routes = [
  { path: 'today', component: TodayPage, title: 'Today · DayMend' },
  { path: 'history', component: HistoryPage, title: 'History · DayMend' },
  { path: 'family', component: FamilyPage, title: 'Family · DayMend' },
  { path: 'settings', component: SettingsPage, title: 'Settings · DayMend' },
  { path: '', redirectTo: 'today', pathMatch: 'full' },
  { path: '**', redirectTo: 'today' },
];
