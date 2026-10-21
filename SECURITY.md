# Security

DPOLens holds an organisation's policies and a record of who asked what, so a weakness in it
should reach the people who can fix it before it reaches anyone who could use it.

## Reporting a vulnerability

Report it privately, in either of two ways:

- **On GitHub**, from this repository's Security tab:
  [report a vulnerability](https://github.com/alkhatibdev/dpolens/security/advisories/new).
  Only you and the maintainers see it.
- **By email**, to security@dpolens.com.

Please do not open an issue, a discussion or a pull request about it first.

Say what you found and how to reproduce it: the version or commit, the steps, what happened,
what you expected, and what somebody could do with it. A proof of concept helps. Test against
an instance you run yourself, never one that belongs to somebody else.

## What happens next

- You get a reply within 3 working days.
- Once the problem is confirmed, the fix goes into the newest release, with a security
  advisory saying what it fixed, which versions are affected and what to do.
- You are credited in the advisory and the release notes, if you want to be.

## Supported versions

Only the newest release gets fixes, security fixes included, as
[Releases and upgrades](https://dpolens.com/docs/releases) says. An older release is fixed by moving to the newest.

## What it covers

The code in this repository, the images its releases publish to GitHub's container registry,
and the law pack archives attached to its releases.

Not covered: how a particular instance is set up, such as one reachable over plain HTTP or one
whose passwords or tokens were shared, and a report from an automated tool with no example of
what it would let somebody do.
