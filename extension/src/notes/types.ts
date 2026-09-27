export interface Identity { project_id: string; document_id: string; project_name: string; document_name: string }
export interface ObjectRef { primitive_id: string; kind: 'component' | 'pad'; label: string; fingerprint: string }
export interface Selection { identity: Identity; objects: ObjectRef[]; unsupported: number }
export interface Board { id: string; name: string; bindings: Identity[] }
export interface Revision { revision: number; body: string; attachment_ids: string[]; created_at: string; origin: string }
export interface Entry { id: string; kind: string; revision: number; revisions: Revision[]; created_at: string }
export interface Note { id: string; board_key: string; identity: Identity; objects: ObjectRef[]; title: string; version: number; status: string; archived: boolean; share_allowed: boolean; entries: Entry[]; updated_at: string }
export interface Attachment { id: string; name: string; caption: string; revision: number; extension: string; data?: string }
export interface Scope { board_key: string; entry_ids: string[]; attachment_ids: string[]; purpose: string; expected_entries?: Record<string, number>; expected_notes?: Record<string, number>; expected_attachments?: Record<string, number> }
export interface Source { note_id: string; entry_id: string; revision: number; body: string; title: string; status: string; kind: string; attachment_ids: string[]; origin: string }
export interface Snapshot { board_key: string; entries: Source[]; attachments: Attachment[]; purpose: string }
export interface Preview { snapshot: Snapshot; snapshot_hash: string }
export interface Block { text: string; heading?: string; source_refs: { note_id: string; entry_id: string; revision: number; quote: string }[]; human_edited?: boolean }
export interface DraftBody { blocks: Block[]; gaps: string[]; human_addition: string; ignored_gaps: boolean }
export interface Draft { id: string; kind: string; version: number; origin: string; snapshot: Snapshot; source_changed: boolean; sharing_changed: boolean; adopted: boolean; confirmation: unknown; ai_original: DraftBody | null; revisions: { version: number; body: DraftBody; origin: string }[] }
export interface Job { id: string; kind: string; status: string; draft_id: string | null; error: string | null; snapshot: Snapshot; config?: { provider: Provider; model: string } }
export type Provider = 'local' | 'deepseek';
export interface ProviderState { selected: Provider; cloud_confirmed: boolean; options: { provider: Provider; model: string; configured: boolean }[] }
