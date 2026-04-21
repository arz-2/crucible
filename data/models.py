"""
SQLAlchemy ORM models for the steel processing recommendation agent database.

Schema design notes:
- Composition, Processing, and Properties are separate tables linked by steel_id.
  The same composition can yield very different properties under different processing routes.
- processing_id is nullable in Properties — many data sources (MatWeb, grade tables)
  give composition + properties with no processing history attached.
- reliability on Source is a 1–5 integer. Weight training data accordingly.
  NIMS = 5, ASM = 5, literature = 3–4, MatWeb = 2–3.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Source — provenance tracking, must be inserted before Steel rows
# ---------------------------------------------------------------------------

class Source(Base):
    __tablename__ = "sources"

    source_id: Mapped[str] = mapped_column(String, primary_key=True)
    source_type: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="One of: NIMS, ASM, MatWeb, literature, proprietary",
    )
    doi: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    pub_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reliability: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        comment="1 (low) to 5 (high). Reflects data quality and measurement rigor.",
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("reliability BETWEEN 1 AND 5", name="ck_reliability_range"),
        CheckConstraint(
            "source_type IN ('NIMS', 'ASM', 'MatWeb', 'literature', 'proprietary')",
            name="ck_source_type_enum",
        ),
    )

    steels: Mapped[List["Steel"]] = relationship("Steel", back_populates="source")


# ---------------------------------------------------------------------------
# Steel — core identity record for a heat / lot / grade entry
# ---------------------------------------------------------------------------

class Steel(Base):
    __tablename__ = "steels"

    steel_id: Mapped[str] = mapped_column(String, primary_key=True)
    grade: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
        comment="Standard grade designation, e.g. 'AISI 4340', 'JIS SCM440'. Null for custom compositions.",
    )
    steel_family: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="One of: carbon, low-alloy, HSLA, stainless, tool, maraging, other",
    )
    source_id: Mapped[str] = mapped_column(
        String, ForeignKey("sources.source_id"), nullable=False
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "steel_family IN ('carbon', 'low-alloy', 'HSLA', 'stainless', 'tool', 'maraging', 'other')",
            name="ck_steel_family_enum",
        ),
    )

    source: Mapped["Source"] = relationship("Source", back_populates="steels")
    composition: Mapped[Optional["Composition"]] = relationship(
        "Composition", back_populates="steel", uselist=False
    )
    processing_records: Mapped[List["Processing"]] = relationship(
        "Processing", back_populates="steel"
    )
    property_records: Mapped[List["Properties"]] = relationship(
        "Properties", back_populates="steel"
    )
    microstructure_records: Mapped[List["Microstructure"]] = relationship(
        "Microstructure", back_populates="steel"
    )


# ---------------------------------------------------------------------------
# Composition — wt% of each element; one row per steel_id
# ---------------------------------------------------------------------------

class Composition(Base):
    """
    All element columns are nullable — sources vary in reporting completeness.
    Missing values should be treated as 'not reported', not zero.
    Do not impute zeros unless you have strong domain justification.
    """

    __tablename__ = "compositions"

    steel_id: Mapped[str] = mapped_column(
        String, ForeignKey("steels.steel_id"), primary_key=True
    )

    # Primary alloying elements — expect high completeness
    C: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="wt%")
    Mn: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="wt%")
    Si: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="wt%")
    Cr: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="wt%")
    Ni: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="wt%")
    Mo: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="wt%")

    # Secondary / microalloying elements — often unreported
    V: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="wt%")
    Nb: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="wt%")
    Ti: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="wt%")
    Al: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="wt%")
    Cu: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="wt%")
    W: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="wt%")
    Co: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="wt%")
    B: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="wt%")
    N: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="wt%")

    # Residuals / tramp elements — often only reported for high-quality data
    P: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="wt%")
    S: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="wt%")

    steel: Mapped["Steel"] = relationship("Steel", back_populates="composition")


# ---------------------------------------------------------------------------
# Processing — heat treatment / thermomechanical route
# One steel can have multiple processing records (e.g., as-rolled vs Q&T variants)
# ---------------------------------------------------------------------------

ROUTE_TYPES = (
    "QT",           # Quench and Temper
    "NT",           # Normalize and Temper
    "TMCP",         # Thermomechanical Controlled Processing
    "anneal",       # Full anneal
    "normalize",    # Normalize only
    "austemper",    # Austempering (bainite)
    "case_harden",  # Carburize, nitride, carbonitriding
    "as_rolled",    # No post-roll heat treatment
    "as_cast",
    "other",
)

QUENCH_MEDIA = ("water", "oil", "polymer", "air", "press_quench", "salt_bath", "other")


class Processing(Base):
    __tablename__ = "processing"

    processing_id: Mapped[str] = mapped_column(String, primary_key=True)
    steel_id: Mapped[str] = mapped_column(
        String, ForeignKey("steels.steel_id"), nullable=False
    )

    route_type: Mapped[str] = mapped_column(
        String, nullable=False, comment="Processing family — see ROUTE_TYPES"
    )

    # Austenitizing
    austenitize_temp_C: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    austenitize_time_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Quench
    quench_medium: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Temper
    temper_temp_C: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    temper_time_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # TMCP-specific
    finishing_temp_C: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    coiling_temp_C: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reduction_ratio: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="Total thickness reduction ratio"
    )

    # Case hardening
    case_depth_mm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            f"route_type IN ({', '.join(repr(r) for r in ROUTE_TYPES)})",
            name="ck_route_type_enum",
        ),
        CheckConstraint(
            f"quench_medium IS NULL OR quench_medium IN ({', '.join(repr(m) for m in QUENCH_MEDIA)})",
            name="ck_quench_medium_enum",
        ),
        # Sanity bounds — catches unit errors (e.g., °F entered as °C)
        CheckConstraint(
            "austenitize_temp_C IS NULL OR (austenitize_temp_C BETWEEN 600 AND 1400)",
            name="ck_austenitize_temp_range",
        ),
        CheckConstraint(
            "temper_temp_C IS NULL OR (temper_temp_C BETWEEN 100 AND 800)",
            name="ck_temper_temp_range",
        ),
    )

    steel: Mapped["Steel"] = relationship("Steel", back_populates="processing_records")
    property_records: Mapped[List["Properties"]] = relationship(
        "Properties", back_populates="processing"
    )
    microstructure_records: Mapped[List["Microstructure"]] = relationship(
        "Microstructure", back_populates="processing"
    )


# ---------------------------------------------------------------------------
# Properties — measured mechanical properties
# Linked to both steel AND processing; processing_id is nullable
# ---------------------------------------------------------------------------

ORIENTATIONS = ("L", "T", "S", "LT", "TL", "unknown")


class Properties(Base):
    __tablename__ = "properties"

    property_id: Mapped[str] = mapped_column(String, primary_key=True)
    steel_id: Mapped[str] = mapped_column(
        String, ForeignKey("steels.steel_id"), nullable=False
    )
    processing_id: Mapped[Optional[str]] = mapped_column(
        String,
        ForeignKey("processing.processing_id"),
        nullable=True,
        comment="Null when processing route is unknown or unrecorded",
    )

    test_standard: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, comment="e.g. 'ASTM E8', 'ISO 6892-1', 'JIS Z2241'"
    )
    test_temp_C: Mapped[float] = mapped_column(
        Float, nullable=False, default=25.0, comment="Test temperature; default 25°C"
    )
    specimen_orientation: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, comment="L=longitudinal, T=transverse, S=short-transverse"
    )

    # Tensile
    yield_strength_MPa: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    uts_MPa: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    elongation_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reduction_area_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Hardness — store in original units, provide all three for coverage
    hardness_HV: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hardness_HRC: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hardness_HB: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Impact
    charpy_J: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    charpy_test_temp_C: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Fracture and fatigue — expect very sparse coverage
    fracture_tough_KIC_MPa_sqrt_m: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    fatigue_limit_MPa: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    __table_args__ = (
        CheckConstraint(
            f"specimen_orientation IS NULL OR specimen_orientation IN ({', '.join(repr(o) for o in ORIENTATIONS)})",
            name="ck_orientation_enum",
        ),
        CheckConstraint(
            "yield_strength_MPa IS NULL OR yield_strength_MPa > 0",
            name="ck_yield_positive",
        ),
        CheckConstraint(
            "uts_MPa IS NULL OR yield_strength_MPa IS NULL OR uts_MPa >= yield_strength_MPa",
            name="ck_uts_gte_yield",
        ),
    )

    steel: Mapped["Steel"] = relationship("Steel", back_populates="property_records")
    processing: Mapped[Optional["Processing"]] = relationship(
        "Processing", back_populates="property_records"
    )


# ---------------------------------------------------------------------------
# Microstructure — expect very sparse; treat as supplementary
# ---------------------------------------------------------------------------

class Microstructure(Base):
    __tablename__ = "microstructure"

    micro_id: Mapped[str] = mapped_column(String, primary_key=True)
    steel_id: Mapped[str] = mapped_column(
        String, ForeignKey("steels.steel_id"), nullable=False
    )
    processing_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("processing.processing_id"), nullable=True
    )

    # Phase fractions (should sum to ~1.0 if all populated)
    martensite_fraction: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bainite_fraction: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ferrite_fraction: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pearlite_fraction: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    retained_austenite_fraction: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )

    grain_size_um: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="Mean grain size in micrometers (ASTM E112)"
    )
    prior_austenite_grain_um: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )

    measurement_method: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, comment="e.g. 'EBSD', 'optical', 'XRD', 'Mossbauer'"
    )

    steel: Mapped["Steel"] = relationship("Steel", back_populates="microstructure_records")
    processing: Mapped[Optional["Processing"]] = relationship(
        "Processing", back_populates="microstructure_records"
    )
