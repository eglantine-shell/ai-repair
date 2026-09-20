from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Rect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x0: float
    top: float
    x1: float
    bottom: float


class Glyph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    rect: Rect


class PagePacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packet_id: str
    pdf_page_index: int = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    page_text: str
    glyphs: list[Glyph]
    packet_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class DirectEditDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_text: str = Field(min_length=1)
    occurrence_index: int = Field(default=0, ge=0)
    corrected_text: str
    category: Literal[
        "wording",
        "grammar",
        "reference",
        "semantic_role",
        "logic",
        "punctuation",
        "repetition",
        "other",
    ]
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def correction_changes_text(self) -> DirectEditDraft:
        if self.original_text == self.corrected_text:
            raise ValueError("corrected_text must differ from original_text")
        return self


class DirectPageReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packet_id: str
    pdf_page_index: int = Field(ge=0)
    edits: list[DirectEditDraft]


class DirectBatchReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str
    reviews: list[DirectPageReview]


class DirectEdit(DirectEditDraft):
    edit_id: str
    packet_id: str
    pdf_page_index: int = Field(ge=0)
    rects: list[Rect] = Field(min_length=1)


class ConsistencyOccurrenceDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packet_id: str
    pdf_page_index: int = Field(ge=0)
    original_text: str = Field(min_length=1)
    occurrence_index: int = Field(default=0, ge=0)


class ConsistencyClusterDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_summary: str = Field(min_length=1)
    relation_type: Literal[
        "same_referent_label_drift",
        "role_granularity_shift",
        "process_name_drift",
        "concept_name_drift",
        "other_local_drift",
    ]
    occurrences: list[ConsistencyOccurrenceDraft] = Field(min_length=2)

    @model_validator(mode="after")
    def distinct_occurrences_and_forms(self) -> ConsistencyClusterDraft:
        keys = {
            (
                item.packet_id,
                item.pdf_page_index,
                item.original_text,
                item.occurrence_index,
            )
            for item in self.occurrences
        }
        if len(keys) != len(self.occurrences):
            raise ValueError("cluster contains duplicate occurrences")
        forms = {compact_text(item.original_text) for item in self.occurrences}
        if len(forms) < 2:
            raise ValueError("cluster requires at least two surface forms")
        return self


class ConsistencyWindowReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_id: str
    clusters: list[ConsistencyClusterDraft]


class ConsistencyCluster(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_id: str
    object_summaries: list[str] = Field(min_length=1)
    relation_types: list[str] = Field(min_length=1)
    occurrences: list[ConsistencyOccurrenceDraft] = Field(min_length=2)


class ConsistencyMark(ConsistencyOccurrenceDraft):
    mark_id: str
    cluster_id: str
    rects: list[Rect] = Field(min_length=1)


def compact_text(text: str) -> str:
    return "".join(character for character in text if not character.isspace())
