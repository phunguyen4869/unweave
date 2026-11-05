# Release 1.5.8 checklist

Temporary note. Delete it once 1.5.8 is out.

The app changes and the version bump are on `guide-and-export-flow`. The website
is already live from `main`, and its guide describes 1.5.8 behaviour, so it won't
match the app until this release ships.

## Test on Windows

Check out `guide-and-export-flow`, build the installer and test the installed app:

- [ ] A fresh install finishes first-run setup, including the Visual C++ runtime.
- [ ] All six stems are selected by default, including Piano and Other.
- [ ] After a separation, Open folder is highlighted with the hint, and it opens
      the project folder with the FLAC files in `stems`.
- [ ] After an export, the success dialog appears instead of the export dialog,
      and Open exports folder opens the right folder.

## Before releasing

- [ ] Look into the two failing tests. Both also fail without these changes:
  - `tests/test_setup_env.py::SetupHealthTests::test_setup_installs_vcruntime_first`
    (the one to check first, because it covers the setup step added in 1.5.7)
  - `tests/test_rename.py::LegacyDataDirTests::test_legacy_folder_is_renamed_with_its_contents`
- [ ] Decide whether the app should also recommend Facebook for error reports. It
      lists GitHub first, and its "Copied" message says "paste it in chat or a GitHub
      issue". The guide already recommends Facebook. If this changes, update the
      guide's copy of that message too.

## Release

- [ ] Merge `guide-and-export-flow` into `main`. The website commits on it match
      what `main` already has.
- [ ] Publish 1.5.8 with `Unweave-Setup-x64.exe` attached. The download button
      looks for that exact file name.
- [ ] Check the version label on the landing page. It can lag by up to an hour;
      use a private window to see it straight away.
