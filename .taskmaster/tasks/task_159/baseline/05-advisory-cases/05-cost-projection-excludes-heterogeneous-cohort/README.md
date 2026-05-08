# 05 — Cost projection excludes heterogeneous cohort (ADV)

**Triggers**: 2 nodes — one priced model, one unpriced/custom. The projection should mark `actual_vs_no_cache_delta` as unavailable with a specific `unavailable_reason`, projection_exclusions populated.

**Mutation contract**: locks the projection-cohort contract from commit `ea5546ac`. If projection cohorts stop excluding heterogeneous rows, the headline savings number can contradict the warning beside it.
