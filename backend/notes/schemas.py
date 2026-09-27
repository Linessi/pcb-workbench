"""Strict public note commands and bounded model output."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Identity(Strict):
    project_id: str = Field(min_length=1, max_length=256)
    document_id: str = Field(min_length=1, max_length=256)
    project_name: str = Field(max_length=300)
    document_name: str = Field(max_length=300)


class ObjectRef(Strict):
    primitive_id: str = Field(min_length=1, max_length=256)
    kind: Literal["component", "pad"]
    label: str = Field(max_length=300)
    fingerprint: str = Field(min_length=1, max_length=4000)


class Binding(Strict):
    identity: Identity
    board_key: str | None = None
    confirm: bool = False


class CreateNote(Strict):
    board_key: str
    identity: Identity
    objects: list[ObjectRef] = Field(default_factory=list, max_length=100)
    title: str = Field(default="", max_length=200)
    body: str = Field(min_length=1, max_length=12000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=12)
    client_id: str = Field(min_length=8, max_length=80)


class NotePatch(Strict):
    expected_version: int
    title: str | None = Field(default=None, max_length=200)
    status: Literal["待确认", "已处理"] | None = None
    archived: bool | None = None
    share_allowed: bool | None = None


class EntryWrite(Strict):
    expected_version: int
    body: str = Field(min_length=1, max_length=12000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=12)


class ObjectBinding(Strict):
    expected_version: int
    identity: Identity
    objects: list[ObjectRef] = Field(min_length=1, max_length=100)


class AttachmentUpload(Strict):
    name: str = Field(max_length=200)
    data: str = Field(max_length=8_400_000)
    caption: str = Field(default="", max_length=2000)


class CaptionPatch(Strict):
    expected_version: int
    caption: str = Field(max_length=2000)


class Scope(Strict):
    board_key: str
    entry_ids: list[str] = Field(min_length=1, max_length=40)
    attachment_ids: list[str] = Field(default_factory=list, max_length=30)
    purpose: str = Field(default="", max_length=1000)
    expected_entries: dict[str, int] = Field(default_factory=dict, max_length=40)
    expected_notes: dict[str, int] = Field(default_factory=dict, max_length=40)
    expected_attachments: dict[str, int] = Field(default_factory=dict, max_length=30)


class JobRequest(Scope):
    snapshot_hash: str
    provider: Literal['local', 'deepseek'] | None = None
    external_confirmed: bool = False


class ProviderSelection(Strict):
    provider: Literal['local', 'deepseek']


class SourceRef(Strict):
    note_id: str
    entry_id: str
    revision: int
    quote: str = Field(min_length=1, max_length=12000)
    attachment_id: str | None = None
    caption_revision: int | None = None


class Block(Strict):
    text: str = Field(min_length=1, max_length=15000)
    source_refs: list[SourceRef] = Field(min_length=1, max_length=40)
    heading: str | None = Field(default=None, max_length=100)


class Generated(Strict):
    blocks: list[Block] = Field(min_length=1, max_length=70)
    gaps: list[str] = Field(default_factory=list, max_length=3)


class Version(Strict):
    expected_version: int


class DraftEdit(Version):
    texts: list[str] = Field(min_length=1, max_length=70)
    human_addition: str = Field(default="", max_length=12000)
    ignored_gaps: bool = False


class ExportRequest(Version):
    draft_id: str
    allow_unconfirmed: bool = False
    text_only: bool = False
    acknowledge_history: bool = False
    share_confirmation: bool = False
