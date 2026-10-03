export interface LocalLibraryTrack {
  /** Stable path relative to the configured library root, with `/` separators. */
  readonly id: string;
  /** Canonical absolute path for bridge-side access; omit from browser-facing payloads. */
  readonly filePath: string;
  readonly title: string;
  readonly artist: string | null;
  readonly extension: string;
}

export interface LocalLibraryReader {
  scan(): Promise<readonly LocalLibraryTrack[]>;
  search(query: string): Promise<readonly LocalLibraryTrack[]>;
}
