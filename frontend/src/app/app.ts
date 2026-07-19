import { Component, inject, signal, computed, OnInit } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { MatToolbarModule } from '@angular/material/toolbar';
import { MatCardModule } from '@angular/material/card';
import { MatTabsModule } from '@angular/material/tabs';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatDividerModule } from '@angular/material/divider';
import { MatTooltipModule } from '@angular/material/tooltip';

import { ApiService } from './api.service';
import { BatchComponent } from './batch.component';
import { CheckReport, RepositoryInfo, ResultCategory, SignalStatus, Verdict } from './models';

@Component({
  selector: 'app-root',
  imports: [
    FormsModule, DecimalPipe, BatchComponent,
    MatToolbarModule, MatCardModule, MatTabsModule, MatButtonModule,
    MatIconModule, MatFormFieldModule, MatInputModule, MatSelectModule,
    MatSlideToggleModule, MatProgressSpinnerModule, MatProgressBarModule,
    MatExpansionModule, MatDividerModule, MatTooltipModule,
  ],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App implements OnInit {
  private api = inject(ApiService);

  // --- Repositorien -------------------------------------------------------
  repos = signal<RepositoryInfo[]>([]);
  selectedRepo = 'prod';

  // --- Eingabe ------------------------------------------------------------
  activeTab = signal(0); // 0=URL, 1=Upload, 2=Node-ID
  imageUrl = '';
  sourcePage = '';
  nodeId = '';
  selectedFile: File | null = null;
  // Einzelprüfung: externe Dienste standardmäßig AN (Backend überspringt sie
  // per Frist, falls ein Dienst nicht rechtzeitig antwortet — kein Abbruch).
  allowExternal = true;
  esUser = '';
  esPassword = '';

  // --- Ergebnis-State -----------------------------------------------------
  loading = signal(false);
  report = signal<CheckReport | null>(null);
  error = signal<string | null>(null);

  ngOnInit(): void {
    this.api.getRepositories().subscribe({
      next: (r) => {
        this.repos.set(r.repositories);
        this.selectedRepo = r.default;
      },
      error: () => {
        // Backend evtl. nicht erreichbar — Standardliste als Fallback.
        this.repos.set([
          { id: 'prod', label: 'Produktion — redaktion.openeduhub.net', base_url: '' },
          { id: 'staging', label: 'Staging — repository.staging.openeduhub.net', base_url: '' },
        ]);
      },
    });
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.selectedFile = input.files?.[0] ?? null;
  }

  submit(): void {
    if (this.loading()) return; // laufende Prüfung nicht mit paralleler überschreiben
    const fd = new FormData();
    const tab = this.activeTab();

    if (tab === 0) {
      if (!this.imageUrl.trim()) return this.fail('Bitte eine Bild-URL angeben.');
      fd.append('mode', 'url');
      fd.append('image_url', this.imageUrl.trim());
      if (this.sourcePage.trim()) fd.append('source_page', this.sourcePage.trim());
    } else if (tab === 1) {
      if (!this.selectedFile) return this.fail('Bitte eine Bilddatei auswählen.');
      fd.append('mode', 'upload');
      fd.append('file', this.selectedFile);
    } else {
      if (!this.nodeId.trim()) return this.fail('Bitte eine Node-ID angeben.');
      fd.append('mode', 'node');
      fd.append('node_id', this.nodeId.trim());
      fd.append('repository', this.selectedRepo);
      if (this.esUser.trim()) fd.append('es_user', this.esUser.trim());
      if (this.esPassword) fd.append('es_password', this.esPassword);
    }
    fd.append('allow_external', String(this.allowExternal));

    this.loading.set(true);
    this.error.set(null);
    this.report.set(null);
    this.api.check(fd).subscribe({
      next: (r) => {
        this.report.set(r);
        this.loading.set(false);
      },
      error: (e) => {
        this.error.set(e?.error?.detail || e?.message || 'Unbekannter Fehler.');
        this.loading.set(false);
      },
    });
  }

  private fail(msg: string): void {
    this.error.set(msg);
    this.report.set(null);
  }

  // --- 4-stufige Ergebnis-Skala -------------------------------------------
  /** CSS-Klassensuffix (Farbe) je Kategorie. */
  categoryClass(c: ResultCategory): string {
    return {
      problematisch: 'red',
      zu_pruefen: 'orange',
      nicht_messbar: 'yellow',
      unproblematisch: 'green',
    }[c] ?? 'yellow';
  }

  categoryIcon(c: ResultCategory): string {
    return {
      problematisch: 'gpp_bad',
      zu_pruefen: 'gpp_maybe',
      nicht_messbar: 'help_center',
      unproblematisch: 'verified_user',
    }[c] ?? 'help_center';
  }

  /** Kurzbeschreibung, was die Kategorie für die Auslieferung bedeutet. */
  categoryMeaning(c: ResultCategory): string {
    return {
      problematisch: 'Warnsignal ohne Gegenbeleg — nicht ausliefern.',
      zu_pruefen: 'Warnhinweis, aber nicht eindeutig — redaktionell klären.',
      nicht_messbar: 'Kein belastbares Signal — Default-Deny, keine automatische Freigabe.',
      unproblematisch: 'Positivnachweis einer freien Lizenz — Freigabe möglich.',
    }[c] ?? '';
  }

  // Reihenfolge + Labels für die Skalen-Legende
  readonly scale: { key: ResultCategory; label: string }[] = [
    { key: 'unproblematisch', label: 'Unproblematisch' },
    { key: 'zu_pruefen', label: 'Zu prüfen' },
    { key: 'nicht_messbar', label: 'Nicht messbar' },
    { key: 'problematisch', label: 'Problematisch' },
  ];

  // --- Anzeige-Helper -----------------------------------------------------
  verdictLabel(v: Verdict): string {
    return {
      red: 'Lizenzpflichtig / geschützt',
      yellow: 'Prüfung nötig',
      green: 'Unkritisch',
      neutral: 'Kein Signal',
      info: 'Information',
    }[v];
  }

  verdictIcon(v: Verdict): string {
    return {
      red: 'gpp_bad',
      yellow: 'gpp_maybe',
      green: 'verified_user',
      neutral: 'help_outline',
      info: 'info',
    }[v];
  }

  statusIcon(s: SignalStatus): string {
    return {
      done: 'check_circle',
      skipped: 'do_not_disturb_on',
      unavailable: 'cloud_off',
      error: 'error',
    }[s];
  }

  statusLabel(s: SignalStatus): string {
    return {
      done: 'geprüft',
      skipped: 'übersprungen',
      unavailable: 'nicht verfügbar',
      error: 'Fehler',
    }[s];
  }

  /** Felder von ExtractedFields als anzeigbare Zeilen (nur befüllte).
   *  Als computed() — sonst würde die Methode mehrfach pro Change-Detection
   *  laufen und das Array jedes Mal neu bauen. */
  readonly fieldRows = computed<{ label: string; value: string; link: boolean }[]>(() => {
    const r = this.report();
    if (!r) return [];
    const f = r.fields;
    const rows: { label: string; value: string; link: boolean }[] = [];
    const add = (label: string, value: unknown, link = false) => {
      if (value !== null && value !== undefined && value !== '') {
        rows.push({ label, value: String(value), link });
      }
    };
    add('Lizenz', f.license_label);
    add('Lizenz-URI', f.license_uri, true);
    add('Rechtehinweis', f.license_field);
    add('Lizenzerwerb-URL', f.acquire_url, true);
    add('Urheber', f.creator);
    add('Bildnachweis', f.credit_text);
    add('Lieferant/Agentur', f.supplier);
    add('Quell-Domain', f.source_domain);
    add('Fundseite', f.source_page, true);
    add('SHA-1', f.sha1);
    add('pHash (dHash)', f.phash);
    add('C2PA', f.c2pa_status);
    return rows;
  });
}
