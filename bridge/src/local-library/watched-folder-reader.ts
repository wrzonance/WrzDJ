import type { Dirent } from "node:fs";
import { readdir, realpath, stat } from "node:fs/promises";
import { basename, extname, join, relative, sep } from "node:path";
import type { LocalLibraryReader, LocalLibraryTrack } from "./types.js";

const AUDIO_EXTENSIONS = new Set([
  ".aac",
  ".aif",
  ".aiff",
  ".alac",
  ".flac",
  ".m4a",
  ".mp3",
  ".ogg",
  ".opus",
  ".wav",
  ".wma",
]);

const IGNORED_DIRECTORY_NAMES = new Set([
  "$recycle.bin",
  ".fseventsd",
  ".spotlight-v100",
  ".temporaryitems",
  ".trashes",
  "system volume information",
]);

interface WatchedFolderFileSystem {
  readdir(path: string, options: { withFileTypes: true }): Promise<Dirent[]>;
  realpath(path: string): Promise<string>;
  stat(path: string): Promise<{ isDirectory(): boolean }>;
}

const defaultFileSystem: WatchedFolderFileSystem = { readdir, realpath, stat };

export class WatchedFolderReader implements LocalLibraryReader {
  constructor(
    private readonly rootPath: string,
    private readonly fileSystem: WatchedFolderFileSystem = defaultFileSystem,
  ) {}

  async scan(): Promise<readonly LocalLibraryTrack[]> {
    let root: string;
    try {
      root = await this.fileSystem.realpath(this.rootPath);
      const rootStats = await this.fileSystem.stat(root);
      if (!rootStats.isDirectory()) {
        throw new Error("configured path is not a directory");
      }
    } catch (error) {
      throw withPathContext("open library folder", this.rootPath, error);
    }

    const tracks: LocalLibraryTrack[] = [];
    await this.readDirectory(root, root, tracks);
    return tracks.sort((left, right) => (left.id < right.id ? -1 : left.id > right.id ? 1 : 0));
  }

  async search(query: string): Promise<readonly LocalLibraryTrack[]> {
    const tracks = await this.scan();
    const normalizedQuery = normalizeSearchText(query);
    if (!normalizedQuery) return tracks;

    return tracks.filter((track) =>
      normalizeSearchText(`${track.artist ?? ""} ${track.title}`).includes(normalizedQuery),
    );
  }

  private async readDirectory(
    root: string,
    directory: string,
    tracks: LocalLibraryTrack[],
  ): Promise<void> {
    let entries;
    try {
      entries = await this.fileSystem.readdir(directory, { withFileTypes: true });
    } catch (error) {
      if (directory !== root && isMissingPath(error)) return;
      throw withPathContext("read library directory", directory, error);
    }

    for (const entry of entries) {
      const filePath = join(directory, entry.name);
      if (entry.isDirectory()) {
        if (isIgnoredDirectory(entry.name)) continue;
        await this.readDirectory(root, filePath, tracks);
      } else if (entry.isFile()) {
        if (entry.name.startsWith("._")) continue;
        const extension = extname(entry.name).toLowerCase();
        if (!AUDIO_EXTENSIONS.has(extension)) continue;
        tracks.push(toTrack(root, filePath, extension));
      }
    }
  }
}

function normalizeSearchText(value: string): string {
  return value.normalize("NFC").toLowerCase().trim();
}

function isIgnoredDirectory(name: string): boolean {
  const normalizedName = name.toLowerCase();
  return (
    IGNORED_DIRECTORY_NAMES.has(normalizedName) ||
    normalizedName === ".trash" ||
    normalizedName.startsWith(".trash-")
  );
}

function isMissingPath(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as NodeJS.ErrnoException).code === "ENOENT"
  );
}

function toTrack(root: string, filePath: string, extension: string): LocalLibraryTrack {
  const filename = basename(filePath, extname(filePath));
  const separatorIndex = filename.indexOf(" - ");
  const artist = separatorIndex > 0 ? filename.slice(0, separatorIndex).trim() : "";
  const title = (separatorIndex > 0 ? filename.slice(separatorIndex + 3) : filename).trim();
  const relativePath = relative(root, filePath).split(sep).join("/");

  return {
    id: relativePath,
    filePath,
    title: title || filename,
    artist: artist || null,
    extension,
  };
}

function withPathContext(action: string, path: string, error: unknown): Error {
  const detail = error instanceof Error ? error.message : String(error);
  return new Error(`Could not ${action} "${path}": ${detail}`, { cause: error });
}
