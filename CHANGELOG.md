# Changelog

## [2.6.3](https://github.com/davidnoyes/givenergy-local/compare/v2.6.2...v2.6.3) (2026-10-09)


### Bug Fixes

* keep mypy passing with HA 2026.10 probatio schema types ([09ca33d](https://github.com/davidnoyes/givenergy-local/commit/09ca33dd7ecc1dd267d28fc5b17f5bf12320294c))
* keep mypy passing with HA 2026.10 probatio schema types ([b7b8116](https://github.com/davidnoyes/givenergy-local/commit/b7b8116e9b7c132a86008269aed9d1b87817f4c0))

## [2.6.2](https://github.com/davidnoyes/givenergy-local/compare/v2.6.1...v2.6.2) (2026-10-02)


### Bug Fixes

* measure clock drift from when the clock registers arrived ([49f190e](https://github.com/davidnoyes/givenergy-local/commit/49f190e72d2f274e4f7daaa072571e708e1bb1b0))
* measure clock drift from when the clock registers arrived ([4d5fe91](https://github.com/davidnoyes/givenergy-local/commit/4d5fe91e106784b75c250b997639c6cf9f1e7c8d))

## [2.6.1](https://github.com/davidnoyes/givenergy-local/compare/v2.6.0...v2.6.1) (2026-09-26)


### Bug Fixes

* bound inverter connect/close, back off reconnects, time-limit commands ([d0d5520](https://github.com/davidnoyes/givenergy-local/commit/d0d55202dc07053d042401e4a57ecd53382acd3f))
* drop duplicate register writes from a command batch ([dd2c0a6](https://github.com/davidnoyes/givenergy-local/commit/dd2c0a6ceeb56676f759c5b7c3f4749c80eabe33))
* port upstream fixes [#148](https://github.com/davidnoyes/givenergy-local/issues/148), [#151](https://github.com/davidnoyes/givenergy-local/issues/151), [#152](https://github.com/davidnoyes/givenergy-local/issues/152) into the fork ([e7d15c7](https://github.com/davidnoyes/givenergy-local/commit/e7d15c77363cb0185753a57c1316a82c5d2c5c92))
* skip PV and consumption updates when a component register is missing ([6eb36ef](https://github.com/davidnoyes/givenergy-local/commit/6eb36efc4f93817e2ec2387460dc59303ed3259a))

## [2.6.0](https://github.com/davidnoyes/givenergy-local/compare/v2.5.1...v2.6.0) (2026-09-26)


### Features

* expose the inverter clock and its drift as diagnostic sensors ([3a7a0a9](https://github.com/davidnoyes/givenergy-local/commit/3a7a0a93e2f61c404bcacdb0cf67e0a92b4b399a))
* expose the inverter clock and its drift as diagnostic sensors ([e966035](https://github.com/davidnoyes/givenergy-local/commit/e966035a55f3d908602f3ec3671eda0ae83f749e))

## [2.5.1](https://github.com/davidnoyes/givenergy-local/compare/v2.5.0...v2.5.1) (2026-09-23)


### Bug Fixes

* energy capacity state class and via_device deprecation on HA 2026.8+ ([f0651ad](https://github.com/davidnoyes/givenergy-local/commit/f0651adcd4298074d7a8896ce5d0b21d22a96927))
* energy capacity state class and via_device deprecation on HA 2026.8+ ([7cf753f](https://github.com/davidnoyes/givenergy-local/commit/7cf753f40c2e1e2d1f543470d9a443e6851da97b))
* restore required Run tests status check ([e176060](https://github.com/davidnoyes/givenergy-local/commit/e1760609b7f611d5a488f0e84f8dbde52a156473))

## [2.2.5](https://github.com/davidnoyes/givenergy-local/compare/v2.2.4...v2.2.5) (2026-03-28)


### Features

* improve reliability, compatibility, and setup UX ([#6](https://github.com/davidnoyes/givenergy-local/pull/6))

## [2.2.4](https://github.com/davidnoyes/givenergy-local/compare/v2.2.3...v2.2.4) (2026-03-08)


### Bug Fixes

* restore required Run tests status check ([e176060](https://github.com/davidnoyes/givenergy-local/commit/e1760609b7f611d5a488f0e84f8dbde52a156473))
