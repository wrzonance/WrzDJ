import { describe, expect, it } from "vitest";
import { parseStreamTitle } from "../../plugins/traktor-broadcast-plugin.js";

describe("parseStreamTitle", () => {
  it("parses standard Artist - Title format", () => {
    const result = parseStreamTitle("StreamTitle='Daft Punk - Around The World';");
    expect(result).toEqual({ artist: "Daft Punk", title: "Around The World" });
  });

  it("parses raw Artist - Title without StreamTitle wrapper", () => {
    const result = parseStreamTitle("Daft Punk - Around The World");
    expect(result).toEqual({ artist: "Daft Punk", title: "Around The World" });
  });

  it("handles title with multiple dashes", () => {
    const result = parseStreamTitle("StreamTitle='The Artist - The Song - Remix';");
    expect(result).toEqual({ artist: "The Artist", title: "The Song - Remix" });
  });

  it("handles title-only (no separator)", () => {
    const result = parseStreamTitle("StreamTitle='Some Track';");
    expect(result).toEqual({ artist: "", title: "Some Track" });
  });

  it("returns null for empty string", () => {
    expect(parseStreamTitle("")).toBeNull();
  });

  it("returns null for whitespace-only", () => {
    expect(parseStreamTitle("   ")).toBeNull();
  });

  it("returns null for empty StreamTitle", () => {
    expect(parseStreamTitle("StreamTitle='';")).toBeNull();
  });

  it("trims whitespace from artist and title", () => {
    const result = parseStreamTitle("StreamTitle='  Artist  -  Title  ';");
    expect(result).toEqual({ artist: "Artist", title: "Title" });
  });
});
