"""
Pydantic v2 schemas for validating ingest records before they touch the database.

Every row entering the DB should be validated through one of these schemas first.
The validators catch unit errors, impossible values, and schema mismatches at the
boundary — before they silently corrupt your training data.

Usage:
    record = PropertiesCreate(**raw_dict)  # raises ValidationError if invalid
    with get_session() as session:
        session.add(Properties(**record.model_dump()))
"""

from __future__ import annotations

import uuid
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_id(prefix: str) -> str:
    """Generate a human-readable prefixed ID."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


SourceType = Literal["NIMS", "ASM", "MatWeb", "literature", "proprietary"]
SteelFamily = Literal["carbon", "low-alloy", "HSLA", "stainless", "tool", "maraging", "other"]
RouteType = Literal[
    "QT", "NT", "TMCP", "anneal", "normalize", "austemper",
    "case_harden", "as_rolled", "as_cast", "other"
]
QuenchMedium = Literal["water", "oil", "polymer", "air", "press_quench", "salt_bath", "other"]
Orientation = Literal["L", "T", "S", "LT", "TL", "unknown"]


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------

class SourceCreate(BaseModel):
    source_id: str = Field(default_factory=lambda: _new_id("src"))
    source_type: SourceType
    doi: Optional[str] = None
    pub_year: Optional[int] = Field(default=None, ge=1900, le=2100)
    reliability: int = Field(default=3, ge=1, le=5)
    notes: Optional[str] = None

    @field_validator("doi")
    @classmethod
    def doi_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.startswith("10."):
            raise ValueError(f"DOI should start with '10.' — got: {v!r}")
        return v


# ---------------------------------------------------------------------------
# Steel
# ---------------------------------------------------------------------------

class SteelCreate(BaseModel):
    steel_id: str = Field(default_factory=lambda: _new_id("steel"))
    grade: Optional[str] = None
    steel_family: SteelFamily
    source_id: str
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Composition
# All wt% values. Validated for physical plausibility, not strict alloy balance.
# ---------------------------------------------------------------------------

_WT_PCT = Field(default=None, ge=0.0, le=100.0)

class CompositionCreate(BaseModel):
    steel_id: str

    # Primary elements
    C:  Optional[float] = _WT_PCT
    Mn: Optional[float] = _WT_PCT
    Si: Optional[float] = _WT_PCT
    Cr: Optional[float] = _WT_PCT
    Ni: Optional[float] = _WT_PCT
    Mo: Optional[float] = _WT_PCT

    # Secondary / microalloying
    V:  Optional[float] = _WT_PCT
    Nb: Optional[float] = _WT_PCT
    Ti: Optional[float] = _WT_PCT
    Al: Optional[float] = _WT_PCT
    Cu: Optional[float] = _WT_PCT
    W:  Optional[float] = _WT_PCT
    Co: Optional[float] = _WT_PCT
    B:  Optional[float] = Field(default=None, ge=0.0, le=0.1)  # B rarely exceeds 0.01 wt%
    N:  Optional[float] = Field(default=None, ge=0.0, le=1.0)

    # Residuals — P capped at 0.1; S raised to 0.4 to allow free-cutting grades (SAE 11xx/12xx, up to ~0.33 wt%)
    P: Optional[float] = Field(default=None, ge=0.0, le=0.1)
    S: Optional[float] = Field(default=None, ge=0.0, le=0.4)

    @model_validator(mode="after")
    def check_mass_balance(self) -> "CompositionCreate":
        """
        Warn if the sum of reported elements far exceeds 100 wt%.
        A small overcount is normal when Fe (balance) is omitted from reporting.
        This catches obvious unit errors (e.g., ppm entered as wt%).
        """
        elements = [self.C, self.Mn, self.Si, self.Cr, self.Ni, self.Mo,
                    self.V, self.Nb, self.Ti, self.Al, self.Cu, self.W,
                    self.Co, self.B, self.N, self.P, self.S]
        total = sum(e for e in elements if e is not None)
        if total > 100.0:
            raise ValueError(
                f"Sum of reported elements ({total:.2f} wt%) exceeds 100%. "
                "Check for unit errors (ppm vs. wt%)."
            )
        return self

    @field_validator("C")
    @classmethod
    def carbon_range(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v > 2.14:
            raise ValueError(
                f"C = {v} wt% exceeds the steel/cast iron boundary (2.14 wt%). "
                "If this is intentional (tool steel, white iron), set steel_family='other'."
            )
        return v


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

class ProcessingCreate(BaseModel):
    processing_id: str = Field(default_factory=lambda: _new_id("proc"))
    steel_id: str

    route_type: RouteType

    austenitize_temp_C: Optional[float] = Field(default=None, ge=600.0, le=1400.0)
    austenitize_time_min: Optional[float] = Field(default=None, ge=0.0)
    quench_medium: Optional[QuenchMedium] = None
    temper_temp_C: Optional[float] = Field(default=None, ge=100.0, le=800.0)
    temper_time_min: Optional[float] = Field(default=None, ge=0.0)

    finishing_temp_C: Optional[float] = Field(default=None, ge=600.0, le=1300.0)
    coiling_temp_C: Optional[float] = Field(default=None, ge=200.0, le=800.0)
    reduction_ratio: Optional[float] = Field(default=None, ge=1.0, le=100.0)

    case_depth_mm: Optional[float] = Field(default=None, ge=0.0, le=10.0)

    notes: Optional[str] = None

    @model_validator(mode="after")
    def qt_requires_quench(self) -> "ProcessingCreate":
        """Q&T without a quench medium is suspicious — flag it."""
        if self.route_type == "QT" and self.quench_medium is None:
            raise ValueError(
                "route_type='QT' should have a quench_medium specified. "
                "If unknown, set quench_medium='other'."
            )
        return self

    @model_validator(mode="after")
    def temper_below_austenitize(self) -> "ProcessingCreate":
        """Tempering above austenitizing temperature is physically nonsensical."""
        if (
            self.temper_temp_C is not None
            and self.austenitize_temp_C is not None
            and self.temper_temp_C >= self.austenitize_temp_C
        ):
            raise ValueError(
                f"temper_temp_C ({self.temper_temp_C}°C) must be below "
                f"austenitize_temp_C ({self.austenitize_temp_C}°C)."
            )
        return self


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class PropertiesCreate(BaseModel):
    property_id: str = Field(default_factory=lambda: _new_id("prop"))
    steel_id: str
    processing_id: Optional[str] = None  # Nullable — many sources omit this

    test_standard: Optional[str] = None
    test_temp_C: float = Field(default=25.0, ge=-200.0, le=800.0)
    specimen_orientation: Optional[Orientation] = None

    yield_strength_MPa: Optional[float] = Field(default=None, ge=0.0, le=3000.0)
    uts_MPa: Optional[float] = Field(default=None, ge=0.0, le=3500.0)
    elongation_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    reduction_area_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)

    hardness_HV: Optional[float] = Field(default=None, ge=0.0, le=2000.0)
    hardness_HRC: Optional[float] = Field(default=None, ge=-10.0, le=70.0)
    hardness_HB: Optional[float] = Field(default=None, ge=0.0, le=700.0)

    charpy_J: Optional[float] = Field(default=None, ge=0.0, le=400.0)
    charpy_test_temp_C: Optional[float] = Field(default=None, ge=-200.0, le=400.0)

    fracture_tough_KIC_MPa_sqrt_m: Optional[float] = Field(default=None, ge=0.0, le=500.0)
    fatigue_limit_MPa: Optional[float] = Field(default=None, ge=0.0, le=3000.0)

    @model_validator(mode="after")
    def uts_gte_yield(self) -> "PropertiesCreate":
        if (
            self.uts_MPa is not None
            and self.yield_strength_MPa is not None
            and self.uts_MPa < self.yield_strength_MPa
        ):
            raise ValueError(
                f"uts_MPa ({self.uts_MPa}) < yield_strength_MPa ({self.yield_strength_MPa}). "
                "Check for swapped columns in source data."
            )
        return self

    @model_validator(mode="after")
    def at_least_one_property(self) -> "PropertiesCreate":
        """Catch rows where all property columns are None — useless for training."""
        fields = [
            self.yield_strength_MPa, self.uts_MPa, self.elongation_pct,
            self.reduction_area_pct, self.hardness_HV, self.hardness_HRC,
            self.hardness_HB, self.charpy_J, self.fracture_tough_KIC_MPa_sqrt_m,
            self.fatigue_limit_MPa,
        ]
        if all(f is None for f in fields):
            raise ValueError("At least one property value must be non-null.")
        return self


# ---------------------------------------------------------------------------
# Microstructure
# ---------------------------------------------------------------------------

class MicrostructureCreate(BaseModel):
    micro_id: str = Field(default_factory=lambda: _new_id("micro"))
    steel_id: str
    processing_id: Optional[str] = None

    martensite_fraction: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    bainite_fraction: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    ferrite_fraction: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    pearlite_fraction: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    retained_austenite_fraction: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    grain_size_um: Optional[float] = Field(default=None, ge=0.0, le=5000.0)
    prior_austenite_grain_um: Optional[float] = Field(default=None, ge=0.0, le=5000.0)
    measurement_method: Optional[str] = None

    @model_validator(mode="after")
    def phase_fractions_sum(self) -> "MicrostructureCreate":
        """Phase fractions should sum to ~1.0 when all are reported."""
        fracs = [
            self.martensite_fraction, self.bainite_fraction,
            self.ferrite_fraction, self.pearlite_fraction,
            self.retained_austenite_fraction,
        ]
        reported = [f for f in fracs if f is not None]
        if len(reported) >= 2:
            total = sum(reported)
            if total > 1.05:
                raise ValueError(
                    f"Phase fractions sum to {total:.3f}, which exceeds 1.0. "
                    "Check for duplicate phases or unit errors (% vs fraction)."
                )
        return self


# ---------------------------------------------------------------------------
# Ingest bundle — full record for a single steel entry
# ---------------------------------------------------------------------------

class SteelIngestBundle(BaseModel):
    """
    A complete ingest payload for one steel entry.
    Use this as the top-level schema when ingesting from a parser or scraper.

    Example:
        bundle = SteelIngestBundle(
            steel=SteelCreate(grade="AISI 4340", steel_family="low-alloy", source_id="src_nims"),
            composition=CompositionCreate(steel_id=..., C=0.40, Mn=0.70, ...),
            processing=[ProcessingCreate(steel_id=..., route_type="QT", ...)],
            properties=[PropertiesCreate(steel_id=..., yield_strength_MPa=1380, ...)],
        )
    """

    steel: SteelCreate
    composition: Optional[CompositionCreate] = None
    processing: List[ProcessingCreate] = Field(default_factory=list)
    properties: List[PropertiesCreate] = Field(default_factory=list)
    microstructure: List[MicrostructureCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def ids_are_consistent(self) -> "SteelIngestBundle":
        """Ensure all sub-records reference the same steel_id."""
        sid = self.steel.steel_id
        if self.composition and self.composition.steel_id != sid:
            raise ValueError("composition.steel_id does not match steel.steel_id")
        for p in self.processing:
            if p.steel_id != sid:
                raise ValueError(f"processing record {p.processing_id} has wrong steel_id")
        for p in self.properties:
            if p.steel_id != sid:
                raise ValueError(f"properties record {p.property_id} has wrong steel_id")
        return self
