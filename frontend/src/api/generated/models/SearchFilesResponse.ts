/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { SearchFileItem } from './SearchFileItem';
export type SearchFilesResponse = {
    items: Array<SearchFileItem>;
    next_cursor?: (string | null);
    query: string;
    total: number;
};
