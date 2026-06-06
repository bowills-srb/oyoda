"""
Knowledge services for the agentic concierge system.

Exports are resolved lazily so callers can import small entry points like
`create_voice_pod` without eagerly loading the full knowledge stack.
"""

from importlib import import_module


_EXPORTS = {
    "VectorStore": ("app.services.knowledge.vector_store", "VectorStore"),
    "get_vector_store": ("app.services.knowledge.vector_store", "get_vector_store"),
    "Document": ("app.services.knowledge.vector_store", "Document"),
    "LibrarianAgent": ("app.services.knowledge.librarian_agent", "LibrarianAgent"),
    "get_librarian_agent": ("app.services.knowledge.librarian_agent", "get_librarian_agent"),
    "LibrarianQuery": ("app.services.knowledge.librarian_agent", "LibrarianQuery"),
    "LibrarianResponse": ("app.services.knowledge.librarian_agent", "LibrarianResponse"),
    "KnowledgeIndexer": ("app.services.knowledge.knowledge_indexer", "KnowledgeIndexer"),
    "get_knowledge_indexer": ("app.services.knowledge.knowledge_indexer", "get_knowledge_indexer"),
    "DocType": ("app.services.knowledge.knowledge_indexer", "DocType"),
    "IndexingResult": ("app.services.knowledge.knowledge_indexer", "IndexingResult"),
    "VoicePod": ("app.services.knowledge.voice_pod", "VoicePod"),
    "VoicePodConfig": ("app.services.knowledge.voice_pod", "VoicePodConfig"),
    "VoicePodContext": ("app.services.knowledge.voice_pod", "VoicePodContext"),
    "VoicePodResponse": ("app.services.knowledge.voice_pod", "VoicePodResponse"),
    "create_voice_pod": ("app.services.knowledge.voice_pod", "create_voice_pod"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
