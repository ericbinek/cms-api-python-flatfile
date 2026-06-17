# Roadmap

The goal is a CMS where content is structured, schema.org-native, and served through a strict, predictable API that is machine-readable by design. That makes it a clean substrate for automation and LLM-driven workflows.

This is a work-in-progress project (v0.3.0). The roadmap is deliberately loose, will grow, and the order can change based on what proves useful. Nothing here is a promise.

## Recently shipped

- CRUD over a schema.org-aligned vocabulary, backed by flat-file JSON storage
- Reference embedding on single-resource reads
- Type-aware sorting, pagination, filtering, and ETag caching
- A named, consistent error format with content-type enforcement

## Planned

- Referential integrity on writes, so a reference cannot point at a missing record
- More entity types as the vocabulary grows
- Duplicate detection on create

## Considering

- A framework-based variant of this server
- Rate limiting

Have a need or an idea? Open an issue. This is built in public and feedback shapes the order.
