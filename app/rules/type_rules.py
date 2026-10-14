"""Type-compatibility rules.

Phase 1 encodes type equivalence in the YAML mappings under
``config/type_mappings`` and the numeric-collapsing logic in
:mod:`app.normalization.datatypes`. This module is reserved for explicit
type-override / lossy-conversion rules in later phases.
"""
