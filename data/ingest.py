"""
Ingest pipeline — validates a SteelIngestBundle and writes it to the database.

This is the single entry point for all data. Nothing writes to the DB
without going through here.

Typical flow:
    1. A source-specific parser (e.g., parsers/nims.py) produces raw dicts
    2. Those dicts are assembled into SteelIngestBundle objects (Pydantic validates)
    3. ingest_bundle() or ingest_bundles() commits them to the DB

Errors are collected per-record and returned rather than crashing the whole batch.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import get_session
from .models import Composition, Microstructure, Processing, Properties, Source, Steel
from .schemas import SteelIngestBundle

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    success: int = 0
    skipped: int = 0
    errors: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"Ingest complete: {self.success} inserted, "
            f"{self.skipped} skipped (duplicates), "
            f"{len(self.errors)} errors"
        )


def ingest_bundle(bundle: SteelIngestBundle, session: Session) -> None:
    """
    Write a validated SteelIngestBundle to the database within an existing session.
    Raises IntegrityError on duplicate primary keys — callers should handle this.
    """
    # Source must already exist — fail explicitly if not
    source = session.get(Source, bundle.steel.source_id)
    if source is None:
        raise ValueError(
            f"source_id '{bundle.steel.source_id}' not found. "
            "Insert the Source record before ingesting steel data."
        )

    steel = Steel(**bundle.steel.model_dump())
    session.add(steel)

    if bundle.composition:
        session.add(Composition(**bundle.composition.model_dump()))

    for proc in bundle.processing:
        session.add(Processing(**proc.model_dump()))

    for prop in bundle.properties:
        session.add(Properties(**prop.model_dump()))

    for micro in bundle.microstructure:
        session.add(Microstructure(**micro.model_dump()))


def ingest_bundles(
    raw_records: List[dict],
    stop_on_error: bool = False,
) -> IngestResult:
    """
    Validate and ingest a list of raw dicts as SteelIngestBundles.

    Each dict should match the SteelIngestBundle schema. Validation errors and
    DB errors are collected per-record. By default, errors are logged and skipped
    rather than crashing the batch.

    Args:
        raw_records:   List of dicts, each representing one steel entry.
        stop_on_error: If True, raise on first error instead of continuing.

    Returns:
        IngestResult with counts and error messages.
    """
    result = IngestResult()

    for i, record in enumerate(raw_records):
        label = record.get("steel", {}).get("steel_id", f"record[{i}]")
        try:
            bundle = SteelIngestBundle(**record)
        except ValidationError as e:
            msg = f"[{label}] Validation failed: {e.error_count()} error(s)\n{e}"
            logger.warning(msg)
            result.errors.append(msg)
            if stop_on_error:
                raise
            continue

        try:
            with get_session() as session:
                ingest_bundle(bundle, session)
            result.success += 1
        except IntegrityError:
            logger.info(f"[{label}] Skipped — duplicate primary key (already in DB)")
            result.skipped += 1
        except Exception as e:
            msg = f"[{label}] DB error: {e}"
            logger.error(msg)
            result.errors.append(msg)
            if stop_on_error:
                raise

    logger.info(str(result))
    return result


def ensure_source(
    source_id: str,
    source_type: str,
    reliability: int = 3,
    doi: Optional[str] = None,
    pub_year: Optional[int] = None,
    notes: Optional[str] = None,
) -> None:
    """
    Upsert a Source record. Call this before ingesting from a new data source.

    This is idempotent — safe to call multiple times with the same source_id.
    """
    with get_session() as session:
        existing = session.get(Source, source_id)
        if existing is None:
            session.add(
                Source(
                    source_id=source_id,
                    source_type=source_type,
                    reliability=reliability,
                    doi=doi,
                    pub_year=pub_year,
                    notes=notes,
                )
            )
            logger.info(f"Source '{source_id}' created.")
        else:
            logger.debug(f"Source '{source_id}' already exists — skipping.")
