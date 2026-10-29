# Public GitHub pull request entry spike

## Claim

For a public GitHub pull request that closes an issue in the same repository, three unauthenticated GitHub REST requests plus two shallow commit fetches can recover the issue statement and exact 40-character base/head commits, while an unknown pull request and unknown commit both fail closed.

## Result

CONFIRMED against Click PR #3299 and issue #3298. The pull request endpoint returned HTTP 200 with base `04ef3a6f473deb2499721a8d11f92a7d2c0912f2` and head `d340b0c1202284a1b9d0ca892549208527d586ce`. The PR body linked `Fix #3298`; the issue endpoint returned HTTP 200 and title `semver.Version as default causing an error`. An unknown PR returned 404.

In a fresh temporary Git repository, `git fetch --depth=1 origin <sha>` retrieved both exact commits and `git cat-file -e <sha>^{commit}` confirmed each object. Fetching an unknown 40-character SHA returned 128 and no commit object.

## Commands

The API spike used Python `urllib` with `Accept: application/vnd.github+json` and requests to:

```text
GET https://api.github.com/repos/pallets/click/pulls/3299
GET https://api.github.com/repos/pallets/click/issues/3298
GET https://api.github.com/repos/pallets/click/pulls/0
```

Commit fetches used:

```sh
git fetch --depth=1 origin 04ef3a6f473deb2499721a8d11f92a7d2c0912f2
git fetch --depth=1 origin d340b0c1202284a1b9d0ca892549208527d586ce
git fetch --depth=1 origin 0000000000000000000000000000000000000000
```

Observed statuses: PR 200, linked issue 200, unknown PR 404, both commit fetches 0, unknown commit fetch nonzero (128).

## Primary sources

- [GitHub REST API: get a pull request](https://docs.github.com/en/rest/pulls/pulls#get-a-pull-request)
- [GitHub REST API: get an issue](https://docs.github.com/en/rest/issues/issues#get-an-issue)
- [Click PR #3299](https://github.com/pallets/click/pull/3299)
- [Click issue #3298](https://github.com/pallets/click/issues/3298)

## Caveat

Only same-repository closing references are in scope. Missing or cross-repository issue references must stop the run and ask for a direct issue URL. Public pull request source can execute code; the UI must stay local and run only after a user explicitly starts it.
