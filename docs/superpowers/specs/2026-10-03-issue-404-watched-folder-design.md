# Issue #404 slice: watched-folder library scanner

**Status:** Approved for the first implementation slice by the coordinating agent on 2026-10-03.

## Goal

Add a bridge-side reader that inventories audio files beneath a DJ-selected folder. The reader is a
small, dependency-free foundation for the local-library HTTP API in issue #404. Each scan reflects
the folder's current contents; this slice does not install a persistent OS watcher.

## Data shape and interface

`LocalLibraryTrack` contains a stable root-relative `id`, an absolute `filePath` for bridge-side
playback, parsed `title`, nullable `artist`, and lowercase `extension`. `LocalLibraryReader` exposes
`scan(): Promise<readonly LocalLibraryTrack[]>` and `search(query: string): Promise<readonly
LocalLibraryTrack[]>`.

`WatchedFolderReader(rootPath)` implements the reader. A recursive scan includes only known audio
extensions, ignores symbolic links, skips common OS trash/system folders and AppleDouble audio
sidecars, and returns deterministic path order. A basename in the form `Artist - Title.ext`
supplies artist and title; other basenames supply title only. IDs use the path relative to the
canonical root, and `filePath` is canonical and absolute. Search rescans, then performs
case-insensitive, NFC-normalized substring matching across combined artist and title. Empty search
returns the full scan.

## Invariants and errors

- Returned canonical file paths remain beneath the canonical selected root; symbolic links are not
  followed.
- Unsupported files are absent, extension matching is case-insensitive, and IDs remain stable for a
  file's relative path within that root.
- Known OS trash/system directories and `._` AppleDouble files are absent. A nested directory that
  disappears during scanning is skipped; other filesystem failures reject with path context and the
  original error as `cause`.
- The scanner does not read file contents or load third-party packages.

The implementation uses Node's `fs/promises` directory entries and path utilities. These APIs are
documented in the [Node.js filesystem reference](https://nodejs.org/api/fs.html) and
[path reference](https://nodejs.org/api/path.html).

## Files and call sites

- `bridge/src/local-library/types.ts` — shared track and reader interfaces.
- `bridge/src/local-library/watched-folder-reader.ts` — scanner and search implementation.
- `bridge/src/__tests__/watched-folder-reader.test.ts` — public behavior tests using temporary
  directories.
- No runtime call site exists yet; the local-library server and pool integration are later slices.

## Excluded from this slice

Rekordbox SQLite, Serato crates, Engine DJ DB, iTunes XML, persistent folder watching, localhost
HTTP/WebSocket endpoints, range streaming, playback position updates, pool UI, and streaming-track
deduplication remain open in issue #404.
