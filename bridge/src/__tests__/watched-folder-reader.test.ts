import { mkdtemp, mkdir, realpath, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, relative, sep } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { WatchedFolderReader } from "../local-library/watched-folder-reader.js";

const temporaryRoots: string[] = [];

async function makeRoot(): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), "wrzdj-library-"));
  temporaryRoots.push(root);
  return root;
}

afterEach(async () => {
  await Promise.all(temporaryRoots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

describe("WatchedFolderReader", () => {
  it("recursively lists supported audio files with stable relative IDs and filename metadata", async () => {
    const root = await makeRoot();
    await mkdir(join(root, "Album"));
    await writeFile(join(root, "Album", "DJ Example - Late Night.FLAC"), "audio");
    await writeFile(join(root, "ambient mix.mp3"), "audio");
    await writeFile(join(root, "cover.jpg"), "image");
    const aliasParent = await makeRoot();
    const rootAlias = join(aliasParent, "library");
    await symlink(root, rootAlias, "dir");
    const canonicalRoot = await realpath(rootAlias);

    const tracks = await new WatchedFolderReader(rootAlias).scan();

    expect(tracks).toEqual([
      {
        id: relative(canonicalRoot, join(canonicalRoot, "Album", "DJ Example - Late Night.FLAC"))
          .split(sep)
          .join("/"),
        filePath: join(canonicalRoot, "Album", "DJ Example - Late Night.FLAC"),
        title: "Late Night",
        artist: "DJ Example",
        extension: ".flac",
      },
      {
        id: "ambient mix.mp3",
        filePath: join(canonicalRoot, "ambient mix.mp3"),
        title: "ambient mix",
        artist: null,
        extension: ".mp3",
      },
    ]);
  });

  it("searches current library tracks case-insensitively by artist and title", async () => {
    const root = await makeRoot();
    await writeFile(join(root, "Soda Stereo - De Música Ligera.mp3"), "audio");
    await writeFile(join(root, "Ambient Loop.wav"), "audio");
    const reader = new WatchedFolderReader(root);

    await expect(reader.search("soda stereo")).resolves.toHaveLength(1);
    await expect(reader.search("soda stereo de música ligera")).resolves.toHaveLength(1);
    await expect(reader.search("loop")).resolves.toHaveLength(1);
    await expect(reader.search("   ")).resolves.toHaveLength(2);

    await writeFile(join(root, "New Addition.ogg"), "audio");
    await expect(reader.search("new addition")).resolves.toHaveLength(1);
  });

  it("ignores audio-like sidecars and known trash or system directories", async () => {
    const root = await makeRoot();
    await mkdir(join(root, "$RECYCLE.BIN"));
    await mkdir(join(root, ".Trashes"));
    await mkdir(join(root, ".Trash-1000"));
    await mkdir(join(root, "System Volume Information"));
    await writeFile(join(root, "._Artist - Song.mp3"), "sidecar");
    await writeFile(join(root, "$RECYCLE.BIN", "Deleted Song.mp3"), "deleted");
    await writeFile(join(root, ".Trashes", "Trashed Song.mp3"), "trashed");
    await writeFile(join(root, ".Trash-1000", "User Trashed Song.mp3"), "trashed");
    await writeFile(join(root, "System Volume Information", "System Audio.mp3"), "system");
    await writeFile(join(root, "Artist - Real Song.mp3"), "audio");

    const tracks = await new WatchedFolderReader(root).scan();

    expect(tracks.map(({ title }) => title)).toEqual(["Real Song"]);
  });

  it("matches accented queries against decomposed Unicode filenames", async () => {
    const root = await makeRoot();
    await writeFile(join(root, "Cafe\u0301 - Mu\u0301sica.mp3"), "audio");

    await expect(new WatchedFolderReader(root).search("Café Música")).resolves.toHaveLength(1);
  });

  it("does not follow symbolic links outside the selected folder", async () => {
    const root = await makeRoot();
    const outside = await makeRoot();
    await writeFile(join(outside, "Outside Track.mp3"), "audio");
    await symlink(outside, join(root, "linked-folder"), "dir");
    await symlink(join(outside, "Outside Track.mp3"), join(root, "linked-track.mp3"), "file");

    await expect(new WatchedFolderReader(root).scan()).resolves.toEqual([]);
  });

  it("surfaces filesystem errors with the root path and original cause", async () => {
    const missingRoot = join(await makeRoot(), "missing");

    await expect(new WatchedFolderReader(missingRoot).scan()).rejects.toMatchObject({
      message: expect.stringContaining(missingRoot),
      cause: expect.objectContaining({ code: "ENOENT" }),
    });
  });
});
