# useful-scripts
Some useful scripts for Windows, Linux, BSD and MacOS

## NewAPI quota reset

`newapi_quota_reset.py` runs once; use cron or another scheduler to invoke it monthly. It reads environment variables by default, or you can switch to the direct configuration block at the top of the script.

```sh
set -a; . ./.env; set +a
python3 newapi_quota_reset.py
```

| Variable | Meaning |
| --- | --- |
| `NEWAPI_URL` | NewAPI server URL |
| `NEWAPI_MANAGEMENT_KEY` | Admin management key |
| `NEWAPI_USERS` | Comma-separated usernames; optional if groups set |
| `NEWAPI_GROUPS` | Comma-separated groups; optional if users set |
| `NEWAPI_QUOTA` | Non-negative quota in NewAPI internal units |
| `NEWAPI_QUOTA_MODE` | `set` sets quota, `top_up` raises it only when below target, `add` adds target quota |
| `NEWAPI_NOTIFY` | `true` by default; writes the global NewAPI Notice after a successful reset (requires Root key) |
| `NEWAPI_NOTICE` | Notice text; defaults to `本月额度已重置。` and replaces the existing global Notice |
