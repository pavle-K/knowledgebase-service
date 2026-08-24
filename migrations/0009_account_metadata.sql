-- Account-level GitHub metadata (age, repo counts, follower counts) - a single
-- row per synced account, refreshed on every sync. Not project-scoped, so no
-- RLS: nothing here names a specific private repo, just aggregate counts that
-- are either already public on the GitHub profile or, for private_repos, no
-- more revealing than a single number. Grants are explicit rather than relying
-- on the `alter default privileges` from 0002/0006 applying to this table.
create table github_account (
    id                 uuid primary key default gen_random_uuid(),
    login              text unique not null,
    name               text,
    bio                text,
    company            text,
    blog               text,
    location           text,
    account_created_at timestamptz not null,
    public_repos       int not null,
    private_repos      int,
    followers          int not null,
    following          int not null,
    synced_at          timestamptz not null default now()
);

grant select, insert, update, delete on github_account to app_rw;
grant select on github_account to app_ro, app_ro_public;
