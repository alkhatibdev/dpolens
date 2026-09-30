"""Packs: reading a law pack from files and loading it into the corpus.

Nothing is re-exported here on purpose. A package that imports its own
submodules for convenience makes a cycle the moment another subject needs one of
its models, which is exactly what happened when the corpus came to point at the
pack a document was loaded from.
"""
