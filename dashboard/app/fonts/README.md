# Dashboard fonts

These Latin-subset variable WOFF2 files are bundled locally so Next.js does not
need a Google Fonts network request during development, build, or browser startup.
Each font keeps the variable weight range used by the dashboard; DM Sans also
retains its optical-size axis.

| Asset | Family | Variable axes | Official font asset |
| --- | --- | --- | --- |
| `dm-sans-latin.woff2` | DM Sans | `opsz` 9–40, `wght` 100–1000 | [Google Fonts](https://fonts.gstatic.com/s/dmsans/v17/rP2Hp2ywxg089UriCZOIHQ.woff2) |
| `plus-jakarta-sans-latin.woff2` | Plus Jakarta Sans | `wght` 200–800 | [Google Fonts](https://fonts.gstatic.com/s/plusjakartasans/v12/LDIoaomQNQcsA88c7O9yZ4KMCoOg4Ko20yw.woff2) |
| `jetbrains-mono-latin.woff2` | JetBrains Mono | `wght` 100–800 | [Google Fonts](https://fonts.gstatic.com/s/jetbrainsmono/v24/tDbV2o-flEEny0FZhsfKu5WU4xD7OwE.woff2) |
| `space-grotesk-latin.woff2` | Space Grotesk | `wght` 300–700 | [Google Fonts](https://fonts.gstatic.com/s/spacegrotesk/v22/V8mDoQDjQSkFtoMM3T6r8E7mPbF4Cw.woff2) |

Each family is licensed under the SIL Open Font License 1.1. The corresponding
upstream license texts are kept in `licenses/` and are sourced from the official
[Google Fonts repository](https://github.com/google/fonts/tree/main/ofl).
