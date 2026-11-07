-- Migration 0006: add valid_until column (temporal validity window).
-- `valid_from` is not a separate column -- `created_at` already serves
-- that role (Sorin's call: a memory is valid from the moment it is
-- recorded; a distinct `valid_from` would just duplicate `created_at`).
-- NULL (the default) means "no expiry", matching every existing row and
-- every caller that doesn't pass it -- fail-open by design, same posture
-- as migration 0005's `abstract` column.
ALTER TABLE memory ADD COLUMN valid_until TEXT;
