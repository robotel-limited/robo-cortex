-- Migration 0005: add abstract column (L0 abstract tier) -- an LLM-generated
-- one-line summary computed synchronously at record_memory() time, NULL if
-- generation failed or hasn't run yet (nullable, fail-open by design).
ALTER TABLE memory ADD COLUMN abstract TEXT;
