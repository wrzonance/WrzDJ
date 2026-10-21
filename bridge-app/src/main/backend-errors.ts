/** Read a useful detail from an error response without trusting its JSON shape. */
export async function readBackendErrorDetail(response: Response, fallback: string): Promise<string> {
  const data = await readJsonBody(response);
  if (data === null || typeof data !== 'object' || Array.isArray(data) || !('detail' in data)) {
    return fallback;
  }
  const detail = data.detail;
  return typeof detail === 'string' && detail.trim().length > 0 ? detail : fallback;
}

/** Add an operation label to transport failures without losing the original cause. */
export async function withErrorContext<T>(
  message: string,
  operation: () => Promise<T>,
): Promise<T> {
  try {
    return await operation();
  } catch (cause) {
    throw new Error(message, { cause });
  }
}

/** Return null for malformed JSON while preserving failures reading the response stream. */
export async function readJsonBody(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch (error) {
    if (error instanceof SyntaxError) return null;
    throw error;
  }
}
