-- Lets a finding be manually acknowledged (e.g. "rotated the key"). Deliberately
-- not auto-cleared on rescan: a rescan re-detecting the same flagged content
-- doesn't mean the human's remediation didn't happen, just that the string is
-- still physically present (e.g. in an old commit). resolved_at is a one-way
-- manual dismissal, not a live "still present" indicator.
alter table secret_scan_findings add column resolved_at timestamptz;
