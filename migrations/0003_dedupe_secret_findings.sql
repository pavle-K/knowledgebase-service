-- Collapse existing duplicate findings (accumulated because every rerun re-scanned
-- unchanged secret-containing chunks) before locking in the uniqueness constraint.
delete from secret_scan_findings a
using secret_scan_findings b
where a.id > b.id
  and a.project_id = b.project_id
  and a.file_path = b.file_path
  and a.rule_id = b.rule_id;

alter table secret_scan_findings
    add constraint secret_scan_findings_project_file_rule_key
    unique (project_id, file_path, rule_id);
