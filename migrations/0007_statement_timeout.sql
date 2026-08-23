-- Bounds cost of LLM-generated SQL at the role level (CLAUDE.md section 3:
-- enforced at the database role, not just application code).
alter role app_ro set statement_timeout = '4s';
alter role app_ro set default_transaction_read_only = on;

alter role app_ro_public set statement_timeout = '4s';
alter role app_ro_public set default_transaction_read_only = on;
