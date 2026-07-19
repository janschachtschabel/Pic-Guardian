import { Component, inject, input, signal, OnDestroy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Subscription, interval, of, switchMap, takeWhile, catchError } from 'rxjs';

import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatDividerModule } from '@angular/material/divider';

import { ApiService } from './api.service';
import { BatchItem, BatchStatus, RepositoryInfo } from './models';

@Component({
  selector: 'app-batch',
  imports: [
    FormsModule,
    MatButtonToggleModule, MatFormFieldModule, MatInputModule,
    MatSelectModule, MatButtonModule, MatIconModule, MatProgressBarModule,
    MatProgressSpinnerModule, MatSlideToggleModule, MatExpansionModule, MatDividerModule,
  ],
  templateUrl: './batch.component.html',
  styleUrl: './batch.component.scss',
})
export class BatchComponent implements OnDestroy {
  private api = inject(ApiService);

  repos = input<RepositoryInfo[]>([]);

  mode = signal<'collection' | 'csv'>('collection');

  // Sammlung
  repo = 'prod';
  collectionNodeId = '';
  maxNodes = 500;
  maxDepth = 8;

  // CSV
  csvFile: File | null = null;
  csvText = '';
  defaultRepo = 'prod';

  // gemeinsam
  allowExternal = false;
  esUser = '';
  esPassword = '';

  starting = signal(false);
  job = signal<BatchStatus | null>(null);
  error = signal<string | null>(null);
  private pollSub?: Subscription;

  // Review-Queue: rote/gelbe Fälle des abgeschlossenen Jobs abarbeiten
  reviewItems = signal<BatchItem[] | null>(null);
  reviewLoading = signal(false);
  /** node_id -> 'pending' | 'ok' | 'duplicate' | 'error' */
  confirmState = signal<Record<string, string>>({});

  ngOnDestroy(): void {
    this.pollSub?.unsubscribe();
  }

  loadReview(): void {
    const j = this.job();
    if (!j || this.reviewLoading()) return;
    this.reviewLoading.set(true);
    this.api.getBatchResults(j.job_id).subscribe({
      next: (res) => {
        this.reviewLoading.set(false);
        const order = { red: 0, yellow: 1 } as Record<string, number>;
        this.reviewItems.set(
          res.results
            .filter((r) => r.verdict === 'red' || r.verdict === 'yellow')
            .sort((a, b) => (order[a.verdict] ?? 9) - (order[b.verdict] ?? 9)),
        );
      },
      error: () => {
        this.reviewLoading.set(false);
        this.fail('Ergebnisse konnten nicht geladen werden.');
      },
    });
  }

  confirm(item: BatchItem): void {
    if (this.confirmState()[item.node_id] === 'pending') return;
    this.setConfirm(item.node_id, 'pending');
    const fd = new FormData();
    fd.append('node_id', item.node_id);
    fd.append('repository', item.repository || 'prod');
    const grund = item.supplier ? `Agentur: ${item.supplier}` : item.headline;
    fd.append('note', `Review-bestätigt (${grund}) — ${item.source_domain || item.node_id}`);
    if (this.esUser.trim()) fd.append('es_user', this.esUser.trim());
    if (this.esPassword) fd.append('es_password', this.esPassword);
    this.api.confirmNode(fd).subscribe({
      next: (res) => this.setConfirm(item.node_id, res.duplicate ? 'duplicate' : 'ok'),
      error: () => this.setConfirm(item.node_id, 'error'),
    });
  }

  private setConfirm(nodeId: string, state: string): void {
    this.confirmState.set({ ...this.confirmState(), [nodeId]: state });
  }

  onCsvSelected(event: Event): void {
    this.csvFile = (event.target as HTMLInputElement).files?.[0] ?? null;
  }

  start(): void {
    if (this.starting() || this.isRunning()) return; // keine parallelen Jobs
    const fd = new FormData();
    fd.append('allow_external', String(this.allowExternal));
    if (this.esUser.trim()) fd.append('es_user', this.esUser.trim());
    if (this.esPassword) fd.append('es_password', this.esPassword);

    let call;
    if (this.mode() === 'collection') {
      if (!this.collectionNodeId.trim()) return this.fail('Bitte eine Sammlungs-Node-ID angeben.');
      fd.append('node_id', this.collectionNodeId.trim());
      fd.append('repository', this.repo);
      fd.append('max_nodes', String(Number(this.maxNodes) || 500));
      fd.append('max_depth', String(Number(this.maxDepth) || 8));
      call = this.api.startCollectionBatch(fd);
    } else {
      if (this.csvFile) fd.append('file', this.csvFile);
      else if (this.csvText.trim()) fd.append('csv_text', this.csvText.trim());
      else return this.fail('Bitte eine CSV-Datei wählen oder CSV-Text eingeben.');
      fd.append('default_repository', this.defaultRepo);
      call = this.api.startCsvBatch(fd);
    }

    this.error.set(null);
    this.job.set(null);
    this.reviewItems.set(null);
    this.confirmState.set({});
    this.starting.set(true);
    this.pollSub?.unsubscribe();
    call.subscribe({
      next: (s) => {
        this.starting.set(false);
        this.job.set(s);
        if (s.status === 'running' || s.status === 'pending') this.poll(s.job_id);
      },
      error: (e) => {
        this.starting.set(false);
        this.fail(e?.error?.detail || e?.message || 'Batch konnte nicht gestartet werden.');
      },
    });
  }

  private poll(jobId: string): void {
    // Ein einzelner transienter Status-Fehler darf das Polling NICHT beenden
    // (sonst gehen die Ergebnisse langlaufender Batches in der UI verloren).
    // catchError im inneren Stream -> äußerer interval-Stream lebt weiter;
    // erst nach mehreren Fehlern in Folge wird aufgegeben.
    let errors = 0;
    this.pollSub = interval(1500)
      .pipe(
        switchMap(() => this.api.getBatchStatus(jobId).pipe(catchError(() => of(null)))),
        takeWhile((s) => {
          if (s) { errors = 0; return s.status === 'running' || s.status === 'pending'; }
          errors += 1;
          return errors < 5;
        }, true),
      )
      .subscribe({
        next: (s) => {
          if (s) {
            this.job.set(s);
          } else if (errors >= 5) {
            const cur = this.job();
            if (cur) this.job.set({ ...cur, status: 'error', error: 'Statusabfrage wiederholt fehlgeschlagen — Batch läuft ggf. im Hintergrund weiter.' });
          }
        },
      });
  }

  private fail(msg: string): void {
    this.error.set(msg);
  }

  exportUrl(kind: 'export.csv' | 'export.json' | 'report'): string {
    const j = this.job();
    return j ? this.api.batchExportUrl(j.job_id, kind) : '';
  }

  templateUrl(): string {
    return this.api.batchTemplateUrl();
  }

  progressValue(): number {
    const j = this.job();
    if (!j || !j.total) return 0;
    return (j.done / j.total) * 100;
  }

  isRunning(): boolean {
    const s = this.job()?.status;
    return s === 'running' || s === 'pending';
  }

  // 4-stufige Ergebnis-Skala für die Batch-Zählung
  readonly scale: { key: 'problematisch' | 'zu_pruefen' | 'nicht_messbar' | 'unproblematisch' | 'fehler';
                    label: string; icon: string; cls: string }[] = [
    { key: 'problematisch', label: 'Problematisch', icon: 'gpp_bad', cls: 'red' },
    { key: 'zu_pruefen', label: 'Zu prüfen', icon: 'gpp_maybe', cls: 'orange' },
    { key: 'nicht_messbar', label: 'Nicht messbar', icon: 'help_center', cls: 'yellow' },
    { key: 'unproblematisch', label: 'Unproblematisch', icon: 'verified_user', cls: 'green' },
    { key: 'fehler', label: 'Fehler', icon: 'error', cls: 'error' },
  ];

  katCount(key: string): number {
    return (this.job()?.kategorien as Record<string, number> | undefined)?.[key] ?? 0;
  }
}
