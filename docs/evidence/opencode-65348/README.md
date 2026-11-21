# OpenCode #65348 web startup replay

| Built web app with native `Array.prototype.toSorted` removed before startup | Result |
| --- | --- |
| Base `cfb1b4afbcd6078c2d2cf5ba43683a681b24588d` | Error boundary reports `toSorted is not a function`. |
| Candidate `f4e9cf9979923d2c1b187d0dd33e9335d329dce6` | Home opens with session search and the fixture session visible. |

The test boots the actual built app in Brave using the repository's Playwright fixture backend. A browser init script removes the missing API. This reproduces the browser capability gap without an Android device. It does not measure support for other APIs on older WebViews.

Run from the source checkout with Bun 1.4.4 and frozen dependencies.

```sh
cd packages/app
cp /path/to/adl-playwright.config.ts .adl-playwright.config.ts
PLAYWRIGHT_PORT=4383 bun run test:e2e:built -- \
  --config .adl-playwright.config.ts --workers 1 --reporter line \
  e2e/regression/home.spec.ts -g 'no native Array.toSorted'
bun test src/runtime/polyfills.test.ts
```

The upstream base uses the new browser assertion unmodified except for equivalent syntax to remove the API before startup. The candidate passes the new unit coverage for a sorted copy, sparse inputs, and the property descriptor.

All 35 tasks passed in the repository's `bun run check`. A wider built Home run passed 22 of 23 cases. The remaining layout-switch case timed out waiting for the Side tabs setting on both the candidate and the untouched base. That check leaves native `toSorted` enabled.
