export interface PublicDocument {
  document_id: string;
  filename: string;
  kind: 'text' | 'markdown' | 'pdf_text' | null;
  status: 'uploaded' | 'parsing' | 'ready' | 'failed' | 'unsupported';
  size_bytes: number;
  content_hash: string;
  revision: number;
  reason: string | null;
}
export interface DocumentPage { documents: PublicDocument[]; total: number; offset: number }
export interface DocumentChunk {
  id: string;
  document_id: string;
  document_version: number;
  index: number;
  text: string;
  page_number: number | null;
  heading: string | null;
  start_offset: number;
  end_offset: number;
  text_hash: string;
}
export interface ChunkPage { document_id: string; chunks: DocumentChunk[]; total: number; offset: number }
export interface DocumentBinding { goal_id: string; node_id: string | null }
export interface CitationSource {
  id: string;
  document_id: string;
  document_version: number;
  chunk_id: string;
  quote: string;
  start_offset: number;
  end_offset: number;
  page_number: number | null;
  heading: string | null;
  text_hash: string;
  status: 'valid' | 'stale' | 'unavailable';
  cited: boolean;
}
export type CitationMap = Record<string, CitationSource>;
export interface LocatedSource {
  source: CitationSource;
  text: string;
  start_offset: number;
  end_offset: number;
  page_number: number | null;
  heading: string | null;
}
export interface SearchResult {
  hits: { chunk: Omit<DocumentChunk, 'text_hash'>; score: number; citation: Omit<CitationSource, 'status' | 'cited' | 'text_hash'> }[];
  empty: boolean;
}
