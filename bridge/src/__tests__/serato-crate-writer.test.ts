import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { afterEach, describe, expect, it } from "vitest";

import {
  renderSeratoCrate,
  writeSeratoCrate,
} from "../plugins/serato-crate-writer.js";

const directories: string[] = [];

function createDirectory(): string {
  const directory = mkdtempSync(join(tmpdir(), "serato-crate-test-"));
  directories.push(directory);
  return directory;
}

afterEach(() => {
  for (const directory of directories.splice(0)) {
    rmSync(directory, { recursive: true, force: true });
  }
});

describe("Serato crate writer", () => {
  it("matches the known crate bytes without adding a UTF-16 terminator", () => {
    const expected = Buffer.from(
      "7672736e000000380031002e0030002f00530065007200610074006f00200053006300720061007400630068004c006900760065002000430072006100740065" +
        "6f74726b0000001e7074726b00000016004d0075007300690063002f0061002e006d00700033",
      "hex",
    );

    expect(renderSeratoCrate([{ volumeRelativePath: "Music/a.mp3" }])).toEqual(expected);
  });

  it("encodes non-ASCII volume-relative paths as UTF-16BE", () => {
    const expectedPath = Buffer.from("0044004a002f6b21", "hex");
    const rendered = renderSeratoCrate([{ volumeRelativePath: "DJ/次" }]);

    expect(rendered.includes(expectedPath)).toBe(true);
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

  it.each([
    "",
    ".",
    "..",
    "../escape",
    "folder/name",
    "folder\\name",
    "bad\nname",
    "a:b",
    "CON",
    "NUL",
    "COM1",
    "CONIN$",
    "safe%%nested",
    "trailing.",
  ])(
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
