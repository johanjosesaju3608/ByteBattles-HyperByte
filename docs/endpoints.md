# ByteBattles API

Interactive documentation: `/docs`. Machine-readable schema: `/openapi.json`.

| Method | Route | Access / purpose |
| --- | --- | --- |
| POST | `/auth/register` | Register a normal user; validated password and email |
| POST | `/auth/login` | OAuth2 form login; rate-limited |
| POST | `/auth/refresh` | Valid refresh token for an existing account/session |
| GET | `/users/me` | Current user, including role |
| PATCH | `/users/me` | Update own profile/password; password change invalidates old tokens |
| DELETE | `/users/me` | Delete own account; last admin protected |
| POST | `/users/bootstrap-admin` | Signed-in user plus private `X-Bootstrap-Token`; only if no admin exists |
| POST | `/users/{username}/promote` | Admin-only promotion |
| GET | `/users/{username}` | Public profile; email only when viewing yourself |
| GET | `/problems/` | Visible problems; admins also see hidden problems |
| GET | `/problems/tags` | Available tags |
| POST | `/problems/tag` | Admin-only tag creation |
| GET | `/problems/{problem_id}` | Problem statement/examples/limits |
| POST | `/problems/` | Admin-only multipart problem/testcase creation |
| DELETE | `/problems/?problem_id=...` | Admin-only deletion with durable storage cleanup |
| POST | `/submissions/` | Signed-in, rate-limited submission; durable pending result |
| GET | `/submissions/` | Submission headers for a username or the signed-in user |
| GET | `/submissions/{submission_id}` | Owner/admin details; source is not public |
| GET | `/healthz` | API/database health |
| GET | `/app` | Browser interface |

Problem-list query parameters: `page`, `limit`, `title`, `difficulty`, `tag`, `metadata`. `metadata=true` returns `{items,total,page,limit,has_more}`. The default remains an array for compatibility. `X-Total-Count` and `X-Has-More` headers are included.

Submission limits return 429 with `Retry-After`. If Redis is unavailable at admission, return 503; already accepted submissions are recovered by the durable dispatcher. Source is limited to 64 KB by default. Hidden testcase input is returned only to administrators.

Problem IDs are 1–6 letters/numbers/underscores/hyphens. ZIP and execution limits are described in `SETUP.md`. Problem metadata/testcase editing and a fourth language are not part of this repair pass.
