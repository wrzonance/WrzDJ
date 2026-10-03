import { mkdtemp, mkdir, rm, symlink, writeFile } from "node:fs/promises";
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

    const tracks = await new WatchedFolderReader(root).scan();

    expect(tracks).toEqual([
      {
        id: relative(root, join(root, "Album", "DJ Example - Late Night.FLAC")).split(sep).join("/"),
        filePath: join(root, "Album", "DJ Example - Late Night.FLAC"),
        title: "Late Night",
        artist: "DJ Example",
        extension: ".flac",
      },
      {
        id: "ambient mix.mp3",
        filePath: join(root, "ambient mix.mp3"),
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
    await expect(reader.search("loop")).resolves.toHaveLength(1);
    await expect(reader.search("   ")).resolves.toHaveLength(2);

    await writeFile(join(root, "New Addition.ogg"), "audio");
    await expect(reader.search("new addition")).resolves.toHaveLength(1);
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
