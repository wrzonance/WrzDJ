export function toggleSetValue<T>(current: ReadonlySet<T>, value: T): Set<T> {
  const next = new Set(current);
  if (next.has(value)) {
    next.delete(value);
  } else {
    next.add(value);
  }
  return next;
}

export function toggleSetContents<T>(current: ReadonlySet<T>, values: readonly T[]): Set<T> {
  return current.size === values.length ? new Set<T>() : new Set(values);
}
