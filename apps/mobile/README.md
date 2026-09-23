# ShipMB Notes for iOS and Android

Expo / React Native implementation of the executable sticky notes. Local notes
autosave, each note has Run and Terminal controls, and output survives toggling
the terminal. Run sends only the current note to an authenticated ShipMBLang
service. This initial build does **not** embed Python on the phone: editing is
offline; execution needs the service connection.

## Current compiler

Compiler **0.2.4**, upstream commit
`db568cee173f9e74da9a07936022f75c935cedfc`, was the latest compiler main commit
verified on 2026-09-23. `src/compiler-snapshot.json` pins its version, commit, and
canonical manifest hash. The service verifies bundled source hashes on startup,
and both endpoints/client reject a mismatched snapshot. No approximate mobile
parser, model translation, or automatic compiler download is used.

When updating the compiler, use the repository's existing bundle workflow,
re-run its conformance tests, regenerate this pin, then release the app and
service together:

```powershell
# From the language repository root
python -c "import json; from pathlib import Path; from shipmblang.mobile_service import compiler_snapshot; Path('apps/mobile/src/compiler-snapshot.json').write_text(json.dumps(compiler_snapshot(), indent=2)+'\n')"
```

## Run locally

Requires Node 22.13+ (Node 24 recommended), Python 3.11+, and npm.

```powershell
cd apps/mobile
npm ci
npm start
```

Use a development build on iOS/Android. `npm run web` provides a browser preview
of the same React Native interface, useful before device testing. Web preview
tokens stay in memory and must be re-entered after a reload. Native builds store
the token in SecureStore; note contents use AsyncStorage and are not encrypted.

Start the development compiler from the language repository root:

```powershell
$env:SHIPMB_MOBILE_TOKEN = python -c "import secrets; print(secrets.token_urlsafe(32))"
$env:SHIPMB_MOBILE_ORIGIN = 'http://localhost:8081' # only for browser preview
python -m shipmblang.mobile_service --host 0.0.0.0 --port 8765
```

Enter the service URL and the same token in the app's Connection screen. For
a physical device, use your computer's LAN address instead of localhost. HTTP
is accepted only by development JavaScript; production requires HTTPS. Native
OS transport policies may require an HTTPS development tunnel as well. Do not
disable production transport security to work around this. The service's
built-in WSGI server is for local development. For remote use, deploy
`shipmblang.mobile_service:create_app()` using a production WSGI server behind
HTTPS, with request-body/connection limits and per-user authentication/rate
limiting before a public launch. The initial token authenticates a private test
service, not a public multi-user account system.

The service does not persist note text or compiler memory. Programs run in a
separate process with a 20-second timeout, the existing general runtime limits,
and no model calls. The mobile request times out after 25 seconds.

## Validate

```powershell
npm run typecheck
npm run lint
npm test
npx expo-doctor
npm run export
```

From the language repository root: `python -m unittest discover -s tests`.

## Device builds and store delivery

The provisional bundle/package ID is `com.zmachinery.shipmbnotes`. Confirm its
ownership before first store registration; changing it later creates a new app.
No Expo project ID, signing keys, Apple team, or Play service-account keys are
invented or committed. Log in with your own Expo account and link the project:

```powershell
npx eas-cli@latest login
npx eas-cli@latest init
npx eas-cli@latest build --platform all --profile development
```

`eas.json` also defines `preview` (internal distribution; Android APK) and
`production` (store builds; Android AAB). After device QA, a hosted HTTPS compiler,
app identifiers, store accounts, privacy disclosures, and signing are ready:

```powershell
npx eas-cli@latest build --platform all --profile production
npx eas-cli@latest submit --platform ios --profile production
npx eas-cli@latest submit --platform android --profile production
```

These commands are provided for the release step; no store submission or signed
native binary is implied by a successful JavaScript export. Test actual keyboard,
safe-area, secure storage, background persistence, and networking on both devices
before release. A public store release also needs a user-friendly provisioned
service/account flow instead of asking every customer to supply a private token.

Official references: [EAS builds](https://docs.expo.dev/build/setup/),
[store submission](https://docs.expo.dev/deploy/submit-to-app-stores/).

Scaffold based on Expo's blank TypeScript template; its notice is in TEMPLATE-LICENSE.
