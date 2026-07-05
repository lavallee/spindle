# Security Policy

## Supported Versions

Only the latest published release of Spindle is supported with security fixes.
There is no long-term-support branch.

## Reporting a Vulnerability

Please report security issues privately by emailing **mlavallee@gmail.com**
rather than opening a public GitHub issue. Include:

- A description of the issue and impact
- Steps to reproduce
- The Spindle version and platform

You should get an acknowledgement within a few days. Once a fix is ready, we
will coordinate disclosure and credit with you.

## Scope

Spindle is local-first. It does not operate a hosted service or phone home. The
main security-sensitive areas are:

- Local state under `$SPINDLE_HOME`
- Symlinks written into harness skill directories
- Optional task/gate/scout integrations configured by environment variables
- Any downstream adapter package that forwards Spindle records to another
  system

Do not expose local queues or generated skill directories to untrusted users
without your own filesystem and process isolation.
