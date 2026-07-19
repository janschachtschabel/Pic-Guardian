import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { BatchResults, BatchStatus, CheckReport, RepositoryList, ReviewConfirmResponse } from './models';

/**
 * Zugriff auf den FastAPI-Prüfdienst über den relativen Pfad `/api`.
 *
 * Dev: der Angular-Dev-Server proxyt `/api` -> http://localhost:8000
 *      (proxy.conf.json, in angular.json als serve.proxyConfig hinterlegt).
 * Prod: `/api` wird per Reverse-Proxy ans Backend geroutet — gleiche Origin,
 *       daher kein CORS und kein Mixed-Content (TLS folgt der Seite).
 */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly base = '/api';

  constructor(private http: HttpClient) {}

  getRepositories(): Observable<RepositoryList> {
    return this.http.get<RepositoryList>(`${this.base}/repositories`);
  }

  check(form: FormData): Observable<CheckReport> {
    return this.http.post<CheckReport>(`${this.base}/check`, form);
  }

  // --- Batch ---
  startCollectionBatch(form: FormData): Observable<BatchStatus> {
    return this.http.post<BatchStatus>(`${this.base}/batch/collection`, form);
  }

  startCsvBatch(form: FormData): Observable<BatchStatus> {
    return this.http.post<BatchStatus>(`${this.base}/batch/csv`, form);
  }

  getBatchStatus(jobId: string): Observable<BatchStatus> {
    return this.http.get<BatchStatus>(`${this.base}/batch/${jobId}`);
  }

  /** Download-/Ansicht-URL eines Batch-Exports. */
  batchExportUrl(jobId: string, kind: 'export.csv' | 'export.json' | 'report'): string {
    return `${this.base}/batch/${jobId}/${kind}`;
  }

  batchTemplateUrl(): string {
    return `${this.base}/batch/template`;
  }

  getBatchResults(jobId: string): Observable<BatchResults> {
    return this.http.get<BatchResults>(`${this.base}/batch/${jobId}/export.json`);
  }

  // --- Review-Queue: bestätigten Problemfall in den Risikospeicher übernehmen ---
  confirmNode(form: FormData): Observable<ReviewConfirmResponse> {
    return this.http.post<ReviewConfirmResponse>(`${this.base}/review/confirm-node`, form);
  }
}
