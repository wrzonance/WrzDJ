import type { RequestSort, SortDirection } from '../types';

export interface RequestListQueryOptions {
  sort?: RequestSort;
  direction?: SortDirection;
  limit?: number;
  offset?: number;
}

export function appendRequestListQueryParams(
  params: URLSearchParams,
  options?: RequestListQueryOptions,
): URLSearchParams {
  const query = new URLSearchParams(params);
  if (options?.sort) query.set('sort', options.sort);
  if (options?.direction) query.set('direction', options.direction);
  if (options?.limit !== undefined) query.set('limit', String(options.limit));
  if (options?.offset !== undefined) query.set('offset', String(options.offset));
  return query;
}
