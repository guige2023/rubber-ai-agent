# P0 Backend Fixes Plan
Created: 2026-05-16

## Target Issues
1. P0-PERF-1: maybe_compact_session blocks event loop
2. P0-PERF-2: get_session_messages opens two DB sessions
3. P0-PERF-3: tiktoken encoder no concurrency lock
4. P0-API-1: API versioning (add /api/v1 prefix)
5. P0-API-2: Request validation layer (Pydantic)
6. P0-API-3: Gateway Handler real implementation
7. P0-DB-1: Add physical foreign keys
8. P0-DB-2: Migration system (formal, not auto_migrate)

## Status
- [ ] P0-PERF-1
- [ ] P0-PERF-2
- [ ] P0-PERF-3
- [ ] P0-API-1
- [ ] P0-API-2
- [ ] P0-API-3
- [ ] P0-DB-1
- [ ] P0-DB-2
