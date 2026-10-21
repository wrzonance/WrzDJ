/** A missing file is expected during session rotation; other I/O errors are not. */
export function isMissingFileError(error: unknown): boolean {
  return typeof error === "object" && error !== null &&
    "code" in error && error.code === "ENOENT";
}
