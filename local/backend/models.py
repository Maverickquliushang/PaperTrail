from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Source = Literal["arxiv", "openalex", "huggingface", "conferences", "openreview"]
SOURCES: tuple[Source, ...] = ("arxiv", "openalex", "huggingface", "conferences", "openreview")
Conference = Literal["NeurIPS", "ICML", "ICLR", "CVPR", "ICCV", "ECCV", "ACL", "EMNLP", "AAAI", "IJCAI", "KDD"]
CONFERENCES: tuple[Conference, ...] = ("NeurIPS", "ICML", "ICLR", "CVPR", "ICCV", "ECCV", "ACL", "EMNLP", "AAAI", "IJCAI", "KDD")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=250)
    sources: list[Source] = Field(default_factory=lambda: list(SOURCES), min_length=1)
    start_date: date | None = None
    end_date: date | None = None
    limit: int = Field(default=10, ge=1, le=50)
    sort: Literal["relevance", "date"] = "relevance"
    conferences: list[Conference] = Field(default_factory=lambda: list(CONFERENCES), min_length=1)

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value or not re.search(r"\w", value):
            raise ValueError("请输入包含文字或数字的研究主题")
        return value

    @field_validator("sources")
    @classmethod
    def unique_sources(cls, value: list[Source]) -> list[Source]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def ordered_dates(self) -> SearchRequest:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("开始日期不能晚于结束日期")
        return self


class Record(BaseModel):
    source: Source
    source_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    url: str
    pdf_url: str | None = None
    venue: str | None = None
    conference: str | None = None
    publication_date: str | None = None
    submitted_date: str | None = None
    updated_date: str | None = None
    listed_date: str | None = None
    retrieved_at: str
    cached: bool = False
    rank: int = 1

    @property
    def filter_date(self) -> str | None:
        return self.submitted_date if self.source == "arxiv" else self.publication_date


class SourceData(BaseModel):
    records: list[Record]
    total: int | None = None
    scanned: int = 0
    limited: bool = False
    note: str = ""
    retrieved_at: str


class SourceStatus(BaseModel):
    source: Source
    state: Literal["pending", "running", "success", "limited", "error", "cancelled"] = "pending"
    count: int = 0
    total: int | None = None
    scanned: int = 0
    note: str = ""
    error_code: str | None = None
    cached_at: str | None = None
    retrieved_at: str | None = None
