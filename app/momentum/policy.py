from momentum.models import SectorDefinition
from momentum.store import MomentumStore


def load_policy_keyword_scores(
    store: MomentumStore,
    sectors: list[SectorDefinition],
    enabled: bool,
) -> dict[str, float]:
    if not enabled:
        return {sector.sector_id: 0.0 for sector in sectors}
    # Policy document collection is intentionally not part of the first MVP.
    # A neutral score avoids penalizing sectors before that data source exists.
    return {sector.sector_id: 50.0 for sector in sectors}
