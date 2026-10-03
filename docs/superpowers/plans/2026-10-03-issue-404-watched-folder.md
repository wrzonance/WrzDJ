# Plan: watched-folder reader

## Interfaces

- `LocalLibraryTrack`: root-relative `id`, absolute `filePath`, `title`, nullable `artist`, lowercase
  extension.
- `LocalLibraryReader.scan(): Promise<readonly LocalLibraryTrack[]>`.
- `LocalLibraryReader.search(query: string): Promise<readonly LocalLibraryTrack[]>`.
- `WatchedFolderReader(rootPath)` recursively scans audio files and searches current results.

## Steps

1. Add boundary tests for recursive extension filtering, filename parsing, deterministic IDs, search,
   symlink exclusion, and filesystem errors. Run the bridge test file and confirm red.
2. Add the interfaces and implement a recursive scanner using Node built-ins only. Keep file paths
   within the canonical root, ignore symlinks, and surface contextual filesystem errors.
3. Run the focused test, bridge TypeScript build, and full bridge test suite; fix any failures.
4. Run `ak verify`, document the implementation in `.ak/why.md`, ship a draft PR, then run the
   remaining review/CI/thread/receipt steps from `.ak/prompt.md`.

## Review focus

- Nested folders and mixed-case extensions produce one stable record per eligible file.
- Symlinked files and directories never escape the selected root.
- An unreadable or missing root fails with context rather than looking like an empty library.
