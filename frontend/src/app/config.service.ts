import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';

export interface AppConfig {
  apiUrl?: string;
  apiGenUrl?: string;
  [key: string]: any;
}

@Injectable({ providedIn: 'root' })
export class AppConfigService {
  private config: AppConfig = {};

  constructor(private http: HttpClient) {}

  load(): Promise<void> {
    return this.http
      .get<AppConfig>('/assets/config.json')
      .toPromise()
      .then(cfg => {
        this.config = cfg || {};
        return;
      })
      .catch(err => {
        console.error('Failed to load config.json, falling back to empty config', err);
        this.config = {};
      });
  }

  get<T = any>(key: string, fallback?: T): T | undefined {
    return (this.config[key] as T) ?? fallback;
  }

  getAll(): AppConfig {
    return this.config;
  }
}
