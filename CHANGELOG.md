# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.14.0] - 2025-11-09
### Changed
- Changed the version to 0.14.0 as 0.13.0 gave me bad luck, all good now

## [0.13.7] - 2025-11-09
### Fixed
- Fixed with CRLF line endings, coverted to LF fixes #23

## [0.13.6] - 2025-11-09
### Fixed
- Fixed with CRLF line endings, coverted to LF fixes #23

## [0.13.5] - 2025-11-09
### Fixed
- Fixed issue with executables not being executable

## [0.13.4] - 2025-11-09
### Removed
- Removed deprecated codenotary field

## [0.13.3] - 2025-11-09
### Removed
- Removed deprecated codenotary field

## [0.13.2] - 2025-11-09
### Removed
- Removed deprecated codenotary field

## [0.13.1] - 2025-11-08
### Removed
- Removed deprecated codenotary field

## [0.13.0] - 2025-11-08
### Changed
- Changed base image from 3.13-alpine3.22 to 3.14-alpine3.22 for aarch64 and amd64 only
### Deprecated
- With the release of Home Assistant 2025.12 support for armhf, armv7 an i386 will be dropped and this addon will remove support for them in the future as well.
  Please update your environment to either aarch64 or amd64.
  More info https://www.home-assistant.io/blog/2025/05/22/deprecating-core-and-supervised-installation-methods-and-32-bit-systems/

## [0.12.0] - 2025-10-02
### Changed
- Bump pyyaml from 6.0.2 to 6.0.3

## [0.11.0] - 2025-06-25
### Changed
- Changed base image from 3.13-alpine3.21 to 3.13-alpine3.22

## [0.10.1] - 2025-01-04
### Changed
- Update README.md

## [0.10.0] - 2024-12-14
### Changed
- Changed base image from 3.13-alpine3.20 to 3.13-alpine3.21

## [0.9.0] - 2024-11-09
### Changed
- Changed base image from 3.12-alpine3.20 to 3.13-alpine3.20

## [0.8.9] - 2024-08-31
### Fixed
- Add 'network' to apparmor to fix the issue with Debian 12 and HA Supervised, closes #20

## [0.8.7] - 2024-08-12
### Changed
- Bump pyyaml from 6.0.1 to 6.0.2

## [0.8.6] - 2024-05-26
### Changed
- Changed base image from 3.12-alpine3.19 to 3.12-alpine3.20

## [0.8.5] - 2024-05-06
### Changed
- Bump paho-mqtt from 2.0.0 to 2.1.0
- Fixed an issue which prevented the addon to get the username and password from Home Assistant, closes #17
- Added logging to see authentication issues for MQTT

## [0.8.4] - 2024-04-07
### Changed
- Improved handling an empty 'measurement.yaml' file

## [0.8.3] - 2024-04-06
### Added
- Added a check to prevent 'NoneType' is not iterable errors

## [0.8.2] - 2024-02-17
### Changed
- Removed sys from imports as no longer used

### Added
- Added more logging information to the log for the addon and for the Python script

## [0.8.0] - 2024-02-12
### Added
- Added support for MQTTv5

## [0.7.0] - 2024-02-12
### Changed
- Bump paho-mqtt from 1.6.1 to 2.0.0
- Added 'mqtt.CallbackAPIVersion.VERSION1'to Client() to support paho-mqtt 2.0.0

## [0.6.4] - 2023-12-15
### Changed
- Changed base image from 3.12-alpine3.18 to 3.12-alpine3.19

## [0.6.3] - 2023-11-04
### Added
- Added codenotary signing

## [0.6.2] - 2023-10-26
### Changed
- Remove args from build.yaml

## [0.6.1] - 2023-10-25
### Changed
- Changed base image from 3.11-alpine3.18 to 3.12-alpine3.18
- Bump some args versions

## [0.6.0] - 2023-07-23
### Fixed
- Updated requirements.txt to fix #9

## [0.5.0] - 2023-06-11
### Changed
- Changed base image from 3.10-alpine3.17 to 3.11-alpine3.18

## [0.4.0] - 2023-04-23
### Changed
- Changed base image from 3.9-alpine3.16 to 3.10-alpine3.17
- Updated dependencies

## [0.3.13] - 2023-01-09
### Fixed
- Fixed permissions issue introduced in 0.3.12

## [0.3.12] - 2023-01-09
### Changed
- Changed example YAML code for Home Assistant to show a different use case as well (thanks @wiljums)

## [0.3.11] - 2022-11-05
### Changed
- Changed example YAML code for Home Assistant to add support for the water meter in the Energy Dashboard (requires Home Assistant 2022.11 or higher)

## [0.3.10] - 2022-06-24
### Changed
- Changed example YAML code for Home Assistant because of new MQTT scheme

## [0.3.9] - 2022-06-22
### Changed
- Changed file permissions to make scripts executable

## [0.3.8] - 2022-06-22
### Changed
- Bump version to 0.3.8

## [0.3.7] - 2022-06-22
### Changed
- Bump version to 0.3.7

## [0.3.6] - 2022-06-22
### Changed
- Updated base image from v3.14 to v3.16
- Made changes to support S6-Overlay v3

## [0.3.5] - 2021-12-29
### Added
- Added URL to Github repository

## [0.3.4] - 2021-12-24
### Changed
- Moved installation instructions back to README.md

## [0.3.3] - 2021-12-24
### Added
- Added DOCS.md for documentation

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
