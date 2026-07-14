"""Parser version for price observations — bump when collectors change semantics."""

# v1: initial collectors (Vast fetched type=bid only).
# v2: Vast fetches on_demand + bid; attrs/eligibility fields populated; parser_version stamped.
CURRENT_PARSER_VERSION = 2
