# Contributing to Acer H340 for Linux

Thanks for helping. Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).

This is a small project with one maintainer. Bug reports, reports from other H340 owners and small pull requests are welcome. For a larger change, or anything that adds a package or a setting, please open an issue first and describe what you want to change. That avoids work on a change that does not fit.

## How to report

- **Bug:** use the [bug form](https://github.com/ehsanenaloo/Acer-h340-linux/issues/new/choose). Give your system, kernel version, package versions, what you expected and what happened. Add the output of `systemctl status h340-leds h340-usb-backup` and the log lines around the problem.
- **Feature:** use the feature form. Say what you want to do and what is missing.
- **Question:** use the question form, after you read the README and INSTALL.md.
- **Security problem:** report it privately. See [SECURITY.md](SECURITY.md). Never use a public issue.

Do not paste passwords, keys or private data into an issue. Disk serial numbers are fine to remove.

## Set up

You need Git and Python 3.

```bash
git clone https://github.com/ehsanenaloo/Acer-h340-linux.git
cd Acer-h340-linux
python3 tools/build_plugin.py
```

The packages appear in `dist/`. Check one with `dpkg-deb -I dist/h340-leds_*.deb`.

## Rules for changes

- **One change per pull request.** Keep it small and explain what and why.
- **Lamp changes need real hardware.** The lamp addresses are measured on the H340. Do not add other boards or guesses. Never change a pin mode, the fan or the watchdog.
- **The copy service never deletes and never overwrites.** A change must keep that.
- **Use only the Python standard library** in the services.
- **Plain words.** Write short sentences in clear English in the docs, comments and messages.
- **Update the changelog.** Add a line under **Unreleased** for anything a user can see.

## Pull requests

Fill in the pull request form. Say which checks you ran and which you could not run, and why.

## License

By contributing you agree that your work is released under the [MIT License](../LICENSE). Changes to the kernel module are released under GPL-2.0-only, like the module.
