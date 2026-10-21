export interface ApiTransport {
  fetch<T>(path: string, options?: RequestInit): Promise<T>;
  publicFetch<T>(url: string, options?: RequestInit): Promise<T>;
  rawFetch(path: string, init?: RequestInit): Promise<Response>;
  downloadCsvBlob(url: string, defaultFilename: string): Promise<boolean | null>;
  kioskSession: string | null;
  onUnauthorized: (() => void) | null;
}
