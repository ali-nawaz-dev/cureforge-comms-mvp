from packages.kg.stub import KnowledgeGraphStub

# Re-export under the more descriptive name. The "Knowledge Graph" stub is
# really a provenance graph for the MVP; the alias gives callers a clearer
# name without breaking existing imports.
ProvenanceGraph = KnowledgeGraphStub

__all__ = ["KnowledgeGraphStub", "ProvenanceGraph"]

