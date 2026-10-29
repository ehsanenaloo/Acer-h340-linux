# Security policy

## Supported versions

| Version | Supported |
|---------|-----------|
| latest `0.x` minor release | Yes |
| older `0.x` minors | No |

## Reporting a vulnerability

Report privately through GitHub's private vulnerability reporting: open <https://github.com/ehsanenaloo/Acer-h340-linux/security/advisories/new> (Security tab, "Report a vulnerability").

If you cannot use GitHub advisories, write to <report@enaloo.com>. Please do not send details in a public place.

Do not open a public issue, pull request or discussion for a suspected vulnerability.

Please include:

- The package and its version.
- The steps to reproduce it.
- The impact you expect.
- Whether the problem is already public.

## Good to know

The lamp service runs as root and writes to I/O registers of the board. The copy service runs as root and mounts removable devices. Reports about these two areas are the most useful.

## What to expect

There is one maintainer. These are goals, not promises.

| Step | Goal |
|------|------|
| Acknowledgement | within 7 days |
| Assessment | within 14 days of the acknowledgement |
| Fix | as soon as practical, in order of severity |

A fix ships as a new release with a published GitHub advisory that credits you, unless you prefer to stay anonymous. Please keep the details private until the advisory is published.
