import { open, stat } from "fs/promises";
import { join } from "path";

const CRATE_VERSION = "1.0/Serato ScratchLive Crate";
const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f-\u009f]/u;

export interface SeratoCrateTrack {
  /** Path relative to the root of the volume containing the audio file. */
  readonly volumeRelativePath: string;
}

function validateCrateName(crateName: string): void {
  if (
    !crateName ||
    crateName !== crateName.trim() ||
    crateName === "." ||
    crateName === ".." ||
    crateName.toLowerCase().endsWith(".crate") ||
    /[\\/]/u.test(crateName) ||
    CONTROL_CHARACTERS.test(crateName)
  ) {
    throw new TypeError("Crate name must be a plain file name without an extension");
  }
}

function validateVolumeRelativePath(value: string): void {
  const segments = value.split("/");
  if (
    !value ||
    value.startsWith("/") ||
    value.includes("\\") ||
    CONTROL_CHARACTERS.test(value) ||
    segments.some((segment) => !segment || segment === "." || segment === "..")
  ) {
    throw new TypeError("Track path must be a safe volume-relative POSIX path");
  }
}

function encodeUtf16BE(value: string): Buffer {
  const output = Buffer.alloc((value.length + 1) * 2);
  for (let index = 0; index < value.length; index += 1) {
    output.writeUInt16BE(value.charCodeAt(index), index * 2);
  }
  return output;
}

function chunk(tag: "vrsn" | "otrk" | "ptrk", payload: Buffer): Buffer {
  const header = Buffer.alloc(8);
  header.write(tag, 0, 4, "ascii");
  header.writeUInt32BE(payload.length, 4);
  return Buffer.concat([header, payload]);
}

/** Render a Serato crate containing already-resolved local audio paths. */
export function renderSeratoCrate(tracks: readonly SeratoCrateTrack[]): Buffer {
  for (const track of tracks) {
    validateVolumeRelativePath(track.volumeRelativePath);
  }

  const entries = tracks.map(({ volumeRelativePath }) =>
    chunk("otrk", chunk("ptrk", encodeUtf16BE(volumeRelativePath))),
  );
  return Buffer.concat([chunk("vrsn", encodeUtf16BE(CRATE_VERSION)), ...entries]);
}

/**
 * Create a new crate file without replacing an existing one.
 * Exclusive creation makes concurrent writes to the same name conflict safely.
 */
export async function writeSeratoCrate(
  directory: string,
  crateName: string,
  tracks: readonly SeratoCrateTrack[],
): Promise<string> {
  validateCrateName(crateName);
  const output = join(directory, `${crateName}.crate`);
  const bytes = renderSeratoCrate(tracks);
  const directoryStat = await stat(directory);
  if (!directoryStat.isDirectory()) {
    throw new TypeError("Crate destination must be an existing directory");
  }

  const file = await open(output, "wx", 0o600);
  try {
    await file.writeFile(bytes);
    await file.sync();
  } finally {
    await file.close();
  }
  return output;
}
