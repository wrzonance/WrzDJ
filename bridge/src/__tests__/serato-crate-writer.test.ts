import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { afterEach, describe, expect, it } from "vitest";

import {
  renderSeratoCrate,
  writeSeratoCrate,
  type SeratoCrateTrack,
} from "../plugins/serato-crate-writer.js";

const directories: string[] = [];

function createDirectory(): string {
  const directory = mkdtempSync(join(tmpdir(), "serato-crate-test-"));
  directories.push(directory);
  return directory;
}

function encodeText(value: string): Buffer {
  const data = Buffer.alloc((value.length + 1) * 2);
  for (let index = 0; index < value.length; index += 1) {
    data.writeUInt16BE(value.charCodeAt(index), index * 2);
  }
  return data;
}

function chunk(tag: string, data: Buffer): Buffer {
  const header = Buffer.alloc(8);
  header.write(tag, 0, 4, "ascii");
  header.writeUInt32BE(data.length, 4);
  return Buffer.concat([header, data]);
}

afterEach(() => {
  for (const directory of directories.splice(0)) {
    rmSync(directory, { recursive: true, force: true });
  }
});

describe("Serato crate writer", () => {
  it("renders the version header and ordered track paths in Serato chunks", () => {
    const tracks: SeratoCrateTrack[] = [
      { volumeRelativePath: "Music/Beyoncé/Álbum/01 - Song.mp3" },
      { volumeRelativePath: "DJ/次/track.flac" },
    ];
    const expected = Buffer.concat([
      chunk("vrsn", encodeText("1.0/Serato ScratchLive Crate")),
      ...tracks.map(({ volumeRelativePath }) =>
        chunk("otrk", chunk("ptrk", encodeText(volumeRelativePath))),
      ),
    ]);

    expect(renderSeratoCrate(tracks)).toEqual(expected);
  });

  it("writes a new crate and returns its path", async () => {
    const directory = createDirectory();
    const tracks = [{ volumeRelativePath: "Music/Artist/Track.mp3" }];

    const outputPath = await writeSeratoCrate(directory, "Summer Set", tracks);

    expect(outputPath).toBe(join(directory, "Summer Set.crate"));
    expect(readFileSync(outputPath)).toEqual(renderSeratoCrate(tracks));
    expect(readdirSync(directory)).toEqual(["Summer Set.crate"]);
  });

  it("refuses to overwrite an existing crate and preserves its contents", async () => {
    const directory = createDirectory();
    const outputPath = join(directory, "Summer Set.crate");
    writeFileSync(outputPath, "existing crate");

    await expect(
      writeSeratoCrate(directory, "Summer Set", [
        { volumeRelativePath: "Music/Artist/Track.mp3" },
      ]),
    ).rejects.toThrow();

    expect(readFileSync(outputPath, "utf8")).toBe("existing crate");
    expect(readdirSync(directory)).toEqual(["Summer Set.crate"]);
  });

  it("allows only one of two concurrent writes to create the same crate", async () => {
    const directory = createDirectory();
    const tracks = [{ volumeRelativePath: "Music/Artist/Track.mp3" }];

    const outcomes = await Promise.allSettled([
      writeSeratoCrate(directory, "Summer Set", tracks),
      writeSeratoCrate(directory, "Summer Set", tracks),
    ]);

    expect(outcomes.filter((outcome) => outcome.status === "fulfilled")).toHaveLength(1);
    expect(outcomes.filter((outcome) => outcome.status === "rejected")).toHaveLength(1);
    expect(readdirSync(directory)).toEqual(["Summer Set.crate"]);
    expect(readFileSync(join(directory, "Summer Set.crate"))).toEqual(
      renderSeratoCrate(tracks),
    );
  });

  it.each(["", ".", "..", "../escape", "folder/name", "folder\\name", "bad\nname"])(
    "rejects unsafe crate name %j",
    async (crateName) => {
      const directory = createDirectory();

      await expect(
        writeSeratoCrate(directory, crateName, [
          { volumeRelativePath: "Music/Artist/Track.mp3" },
        ]),
      ).rejects.toThrow();

      expect(readdirSync(directory)).toEqual([]);
    },
  );

  it.each([
    "",
    "/Music/Artist/Track.mp3",
    "Music/../outside.mp3",
    "Music\\Artist\\Track.mp3",
    "Music/Artist/\u0000Track.mp3",
  ])("rejects unsafe volume-relative path %j", (volumeRelativePath) => {
    expect(() => renderSeratoCrate([{ volumeRelativePath }])).toThrow();
  });
});
