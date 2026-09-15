/**
 * Tests for Serato Session File Binary Parser
 *
 * Tests the binary parsing functions in isolation using hand-crafted buffers
 * that replicate Serato's session file format.
 */
import { describe, it, expect } from "vitest";
import {
  decodeUtf16BE,
  parseAdatContent,
  parseSessionBytes,
  findLatestSessionFile,
  getDefaultSeratoPath,
} from "../plugins/serato-session-parser.js";

// ---------------------------------------------------------------------------
// Helpers to build binary test data
// ---------------------------------------------------------------------------

/** Encode a string to UTF-16 Big-Endian with null terminator. */
function encodeUtf16BE(str: string): Buffer {
  const buf = Buffer.alloc((str.length + 1) * 2);
  for (let i = 0; i < str.length; i++) {
    buf.writeUInt16BE(str.charCodeAt(i), i * 2);
  }
  // Last 2 bytes are already 0x00 0x00 (null terminator)
  return buf;
}

/** Build a single ADAT field: u32 field_id + u32 length + data. */
function buildField(fieldId: number, data: Buffer): Buffer {
  const header = Buffer.alloc(8);
  header.writeUInt32BE(fieldId, 0);
  header.writeUInt32BE(data.length, 4);
  return Buffer.concat([header, data]);
}

/** Build an ADAT field with a UTF-16 BE text value. */
function buildTextField(fieldId: number, text: string): Buffer {
  return buildField(fieldId, encodeUtf16BE(text));
}

/** Build an ADAT field with a u32 value. */
function buildU32Field(fieldId: number, value: number): Buffer {
  const data = Buffer.alloc(4);
  data.writeUInt32BE(value, 0);
  return buildField(fieldId, data);
}

/** Wrap content in a chunk with 4-byte ASCII tag + 4-byte BE length. */
function wrapChunk(tag: string, content: Buffer): Buffer {
  const header = Buffer.alloc(8);
  header.write(tag, 0, 4, "ascii");
  header.writeUInt32BE(content.length, 4);
  return Buffer.concat([header, content]);
}

/** Build a complete OENT chunk wrapping an ADAT with the given fields. */
function buildOentChunk(fields: Buffer[]): Buffer {
  const adatContent = Buffer.concat(fields);
  const adatChunk = wrapChunk("adat", adatContent);
  return wrapChunk("oent", adatChunk);
}

// ---------------------------------------------------------------------------
// decodeUtf16BE
// ---------------------------------------------------------------------------

describe("decodeUtf16BE", () => {
  it("decodes ASCII text", () => {
    const buf = encodeUtf16BE("Hello");
    expect(decodeUtf16BE(buf)).toBe("Hello");
  });

  it("decodes accented characters", () => {
    const buf = encodeUtf16BE("Beyoncé");
    expect(decodeUtf16BE(buf)).toBe("Beyoncé");
  });

  it("decodes CJK characters", () => {
    const buf = encodeUtf16BE("音楽");
    expect(decodeUtf16BE(buf)).toBe("音楽");
  });

  it("stops at null terminator", () => {
    // "Hi" followed by null then "XX"
    const buf = Buffer.alloc(10);
    buf.writeUInt16BE("H".charCodeAt(0), 0);
    buf.writeUInt16BE("i".charCodeAt(0), 2);
    buf.writeUInt16BE(0, 4); // null
    buf.writeUInt16BE("X".charCodeAt(0), 6);
    buf.writeUInt16BE("X".charCodeAt(0), 8);
    expect(decodeUtf16BE(buf)).toBe("Hi");
  });

  it("returns empty string for empty buffer", () => {
    expect(decodeUtf16BE(Buffer.alloc(0))).toBe("");
  });

  it("returns empty string for buffer with only null terminator", () => {
    expect(decodeUtf16BE(Buffer.alloc(2))).toBe("");
  });
});

// ---------------------------------------------------------------------------
// parseAdatContent
// ---------------------------------------------------------------------------

describe("parseAdatContent", () => {
  it("parses all fields from a complete ADAT chunk", () => {
    const fields = [
      buildTextField(2, "Around The World"),
      buildTextField(6, "Daft Punk"),
      buildTextField(8, "Homework"),
      buildTextField(10, "Electronic"),
      buildTextField(13, "123.45"),
      buildTextField(29, "Am"),
      buildU32Field(31, 1700000000),
      buildU32Field(52, 2),
    ];

    const result = parseAdatContent(Buffer.concat(fields));

    expect(result.title).toBe("Around The World");
    expect(result.artist).toBe("Daft Punk");
    expect(result.album).toBe("Homework");
    expect(result.genre).toBe("Electronic");
    expect(result.bpm).toBeCloseTo(123.45);
    expect(result.key).toBe("Am");
    expect(result.startTime).toBe(1700000000);
    expect(result.deck).toBe(2);
  });

  it("returns defaults for missing fields", () => {
    const fields = [buildTextField(2, "Some Track")];
    const result = parseAdatContent(Buffer.concat(fields));

    expect(result.title).toBe("Some Track");
    expect(result.artist).toBe("");
    expect(result.album).toBe("");
    expect(result.genre).toBe("");
    expect(result.bpm).toBe(0);
    expect(result.key).toBe("");
    expect(result.deck).toBe(0);
    expect(result.startTime).toBe(0);
  });

  it("handles empty buffer", () => {
    const result = parseAdatContent(Buffer.alloc(0));

    expect(result.title).toBe("");
    expect(result.artist).toBe("");
    expect(result.deck).toBe(0);
  });

  it("skips unknown field IDs gracefully", () => {
    const fields = [
      buildTextField(999, "unknown"),
      buildTextField(2, "Title"),
    ];
    const result = parseAdatContent(Buffer.concat(fields));

    expect(result.title).toBe("Title");
  });

  it("handles non-numeric BPM text", () => {
    const fields = [buildTextField(13, "not-a-number")];
    const result = parseAdatContent(Buffer.concat(fields));

    expect(result.bpm).toBe(0);
  });

  it("parses integer BPM text", () => {
    const fields = [buildTextField(13, "128")];
    const result = parseAdatContent(Buffer.concat(fields));

    expect(result.bpm).toBe(128);
  });

  it("parses fields in any order", () => {
    // Artist before title (reversed from typical order)
    const fields = [
      buildTextField(6, "Artist First"),
      buildU32Field(52, 3),
      buildTextField(2, "Title Second"),
    ];
    const result = parseAdatContent(Buffer.concat(fields));

    expect(result.artist).toBe("Artist First");
    expect(result.title).toBe("Title Second");
    expect(result.deck).toBe(3);
  });

  it("handles truncated field data", () => {
    // Field header says 100 bytes but buffer ends before that
    const header = Buffer.alloc(8);
    header.writeUInt32BE(2, 0); // FIELD_TITLE
    header.writeUInt32BE(100, 4); // claims 100 bytes

    const result = parseAdatContent(header);
    expect(result.title).toBe(""); // Should not crash
  });
});

// ---------------------------------------------------------------------------
// parseSessionBytes
// ---------------------------------------------------------------------------

describe("parseSessionBytes", () => {
  it("parses a single OENT/ADAT entry", () => {
    const chunk = buildOentChunk([
      buildTextField(2, "Strobe"),
      buildTextField(6, "Deadmau5"),
      buildU32Field(52, 1),
    ]);

    const result = parseSessionBytes(chunk);

    expect(result.entries).toHaveLength(1);
    expect(result.entries[0]!.title).toBe("Strobe");
    expect(result.entries[0]!.artist).toBe("Deadmau5");
    expect(result.entries[0]!.deck).toBe(1);
    expect(result.bytesConsumed).toBe(chunk.length);
  });

  it("parses multiple OENT entries", () => {
    const chunk1 = buildOentChunk([
      buildTextField(2, "Track A"),
      buildTextField(6, "Artist A"),
      buildU32Field(52, 1),
    ]);
    const chunk2 = buildOentChunk([
      buildTextField(2, "Track B"),
      buildTextField(6, "Artist B"),
      buildU32Field(52, 2),
    ]);

    const buf = Buffer.concat([chunk1, chunk2]);
    const result = parseSessionBytes(buf);

    expect(result.entries).toHaveLength(2);
    expect(result.entries[0]!.title).toBe("Track A");
    expect(result.entries[0]!.deck).toBe(1);
    expect(result.entries[1]!.title).toBe("Track B");
    expect(result.entries[1]!.deck).toBe(2);
    expect(result.bytesConsumed).toBe(buf.length);
  });

  it("skips non-OENT chunks", () => {
    const unknownChunk = wrapChunk("vrsn", Buffer.from("1.0"));
    const oentChunk = buildOentChunk([
      buildTextField(2, "Real Track"),
      buildTextField(6, "Real Artist"),
    ]);

    const result = parseSessionBytes(Buffer.concat([unknownChunk, oentChunk]));

    expect(result.entries).toHaveLength(1);
    expect(result.entries[0]!.title).toBe("Real Track");
  });

  it("returns empty result for empty buffer", () => {
    const result = parseSessionBytes(Buffer.alloc(0));
    expect(result.entries).toEqual([]);
    expect(result.bytesConsumed).toBe(0);
  });

  it("handles truncated chunk gracefully and reports partial consumption", () => {
    // Just a tag + length but no content (claims 1000 bytes)
    const buf = Buffer.alloc(8);
    buf.write("oent", 0, 4, "ascii");
    buf.writeUInt32BE(1000, 4); // claims 1000 bytes

    const result = parseSessionBytes(buf);
    expect(result.entries).toEqual([]);
    expect(result.bytesConsumed).toBe(0); // nothing was fully consumed
  });

  it("reports correct bytesConsumed when trailing chunk is incomplete", () => {
    const complete = buildOentChunk([
      buildTextField(2, "Complete Track"),
      buildTextField(6, "Complete Artist"),
    ]);

    // Incomplete trailing chunk (header only, no data)
    const incomplete = Buffer.alloc(8);
    incomplete.write("oent", 0, 4, "ascii");
    incomplete.writeUInt32BE(500, 4);

    const buf = Buffer.concat([complete, incomplete]);
    const result = parseSessionBytes(buf);

    expect(result.entries).toHaveLength(1);
    expect(result.entries[0]!.title).toBe("Complete Track");
    // Only the complete chunk should be counted
    expect(result.bytesConsumed).toBe(complete.length);
  });

  it("parses session with vrsn header followed by oent chunks", () => {
    // Real Serato files start with a vrsn chunk, then oent chunks
    const vrsnContent = encodeUtf16BE("81.0");
    const vrsnChunk = wrapChunk("vrsn", vrsnContent);

    const oent1 = buildOentChunk([
      buildTextField(2, "First"),
      buildTextField(6, "DJ A"),
      buildU32Field(52, 1),
    ]);
    const oent2 = buildOentChunk([
      buildTextField(2, "Second"),
      buildTextField(6, "DJ B"),
      buildU32Field(52, 2),
    ]);

    const result = parseSessionBytes(
      Buffer.concat([vrsnChunk, oent1, oent2])
    );

    expect(result.entries).toHaveLength(2);
    expect(result.entries[0]!.title).toBe("First");
    expect(result.entries[1]!.title).toBe("Second");
  });

  it("handles incremental parsing of appended bytes", () => {
    // Simulate reading only the newly-appended portion
    const chunk1 = buildOentChunk([
      buildTextField(2, "Already Read"),
      buildTextField(6, "Old Artist"),
    ]);
    const chunk2 = buildOentChunk([
      buildTextField(2, "New Track"),
      buildTextField(6, "New Artist"),
    ]);

    const fullBuffer = Buffer.concat([chunk1, chunk2]);

    // Parse only the "new" portion (starting from chunk2's offset)
    const newBytes = fullBuffer.subarray(chunk1.length);
    const result = parseSessionBytes(newBytes);

    expect(result.entries).toHaveLength(1);
    expect(result.entries[0]!.title).toBe("New Track");
    expect(result.bytesConsumed).toBe(chunk2.length);
  });
});

// ---------------------------------------------------------------------------
// getDefaultSeratoPath
// ---------------------------------------------------------------------------

describe("getDefaultSeratoPath", () => {
  it("returns a path containing _Serato_ and Sessions", () => {
    const path = getDefaultSeratoPath();
    expect(path).toContain("_Serato_");
    expect(path).toContain("Sessions");
  });
});

// ---------------------------------------------------------------------------
// findLatestSessionFile
// ---------------------------------------------------------------------------

describe("findLatestSessionFile", () => {
  it("returns null for non-existent directory", () => {
    expect(findLatestSessionFile("/nonexistent/path/xyz")).toBeNull();
  });

  it("returns null for empty directory", async () => {
    const fs = await import("fs");
    const os = await import("os");
    const path = await import("path");

    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "serato-test-"));
    try {
      expect(findLatestSessionFile(tmpDir)).toBeNull();
    } finally {
      fs.rmSync(tmpDir, { recursive: true });
    }
  });

  it("returns the most recent .session file", async () => {
    const fs = await import("fs");
    const os = await import("os");
    const path = await import("path");

    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "serato-test-"));
    try {
      // Create two session files with different mtimes
      const older = path.join(tmpDir, "old.session");
      const newer = path.join(tmpDir, "new.session");

      fs.writeFileSync(older, "old");
      // Ensure different mtime
      await new Promise((resolve) => setTimeout(resolve, 50));
      fs.writeFileSync(newer, "new");

      const result = findLatestSessionFile(tmpDir);
      expect(result).toBe(newer);
    } finally {
      fs.rmSync(tmpDir, { recursive: true });
    }
  });

  it("ignores non-.session files", async () => {
    const fs = await import("fs");
    const os = await import("os");
    const path = await import("path");

    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "serato-test-"));
    try {
      fs.writeFileSync(path.join(tmpDir, "data.crate"), "crate");
      fs.writeFileSync(path.join(tmpDir, "history.session"), "session");

      const result = findLatestSessionFile(tmpDir);
      expect(result).toBe(path.join(tmpDir, "history.session"));
    } finally {
      fs.rmSync(tmpDir, { recursive: true });
    }
  });
});
