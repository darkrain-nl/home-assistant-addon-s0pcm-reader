# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.2] - 2021-12-24
### Added
- Added apparmor.txt file for increased security

### Removed
- Removed dailystat from s0pcm_config.conf, this means we no longer get a CSV file with the daily count

## [0.3.1] - 2021-12-23
### Fixed
- Fixed a bug that caused the add-on to fail after rebooting Home Assistant (https://github.com/darkrain-nl/home-assistant-addon-s0pcm-reader/issues/3)

## [0.3.0] - 2021-12-23
### Changed
- Changed data store folder to /share/s0pcm to make it persistant (not sure if this is the best way...)

## [0.2.0] - 2021-12-22
### Added
- make it possible to use the 5 meter version as well

## [0.1.0] - 2021-12-22
### Added
- Initial local test version

[Unreleased]:
[0.2.0]: First version on Github
[0.1.0]: Local first test
