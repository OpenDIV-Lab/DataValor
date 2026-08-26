"""Small, dependency-free catalog of DataValor's public module boundaries."""

from dataclasses import dataclass
from enum import Enum


class ValueStage(str, Enum):
    """Stages in the data valorization lifecycle."""

    DISCOVERY = "value_discovery"
    CIRCULATION = "value_circulation"
    REALIZATION = "value_realization"


@dataclass(frozen=True)
class ModuleSpec:
    """Metadata for a top-level research module."""

    order: int
    display_name: str
    import_path: str
    stage: ValueStage
    responsibility: str


MODULES = (
    ModuleSpec(0, "DataGov", "datavalor.data_gov", ValueStage.DISCOVERY, "data governance"),
    ModuleSpec(1, "DataProf", "datavalor.data_prof", ValueStage.DISCOVERY, "data profiling"),
    ModuleSpec(2, "DataEval", "datavalor.data_eval", ValueStage.DISCOVERY, "data evaluation"),
    ModuleSpec(3, "DataValue", "datavalor.data_value", ValueStage.DISCOVERY, "data valuation"),
    ModuleSpec(4, "DataMarket", "datavalor.data_market", ValueStage.CIRCULATION, "data markets"),
    ModuleSpec(5, "DataPrice", "datavalor.data_price", ValueStage.CIRCULATION, "data pricing"),
    ModuleSpec(6, "DataQuery", "datavalor.data_query", ValueStage.REALIZATION, "data applications"),
)

