# EVE Loot & Jita Market Analyzer

Windows desktop loot valuation and blueprint manufacturing calculator. Version 1.5 includes a black and red Pochven-inspired theme and complete Polish/English interface localization.

## Run from source

This repository contains the source code and bundled data. Generated Windows installers and portable ZIP packages are distributed separately from the source code. On Windows 10/11 with Python 3.11 or later:

```powershell
python -m pip install -r requirements.txt
python main.py
```

## Single-file Windows installer

Download `EveLootAnalyzer-Setup-1.5.exe` from a published GitHub release, run it, choose English or Polish, and follow the wizard. The installer includes Python and all application libraries. It installs for the current user, adds a Start menu entry, and offers a desktop shortcut. Windows Settings can uninstall the app. Updates and uninstall preserve profiles and sessions in `%LOCALAPPDATA%\EveLootAnalyzer`.

The installer language controls the wizard; use the two flags in the app to select the interface language. The installer is not digitally signed.

## Portable Windows package and language selection

After building the Windows package, run `Start.bat` in the project folder, or `dist-v1.5/EveLootAnalyzer/EveLootAnalyzer.exe`.
For another computer, extract **all** of `dist-v1.5/EveLootAnalyzer-Windows.zip`. Keep the `_internal` folder next to the executable. Python is not required.

Optional: `Install.bat` installs the app under `%LOCALAPPDATA%\Programs\EveLootAnalyzer` and creates a desktop shortcut, without administrator privileges. Close the app before reinstalling.

Use the flags in the upper-right corner: Polish for Polski, British for English. Changes apply immediately and are remembered. Switching languages preserves pasted loot, results, filters and sorting. EVE item and skill names retain their original names.

## Analyze loot

1. Set your trade and industry skills, raw Caldari standings, clone state and material purchasing method in **Profile and settings**.
2. Paste inventory text into **Analyze loot**, then click **Analyze market**.
3. Double-click an item to inspect buy fills, sell depth, history, confidence, liquidity and recommendations.
4. Double-click a blueprint to set remaining runs, runs per copy, ME and TE. Identical parameters apply to every copy in that stack. Analyze copies separately when their parameters differ.
5. Use **Save session** to preserve the valuation. Add items or blueprint products to **Watchlist** to track targets.

Empty inventory quantity cells count as one item; invalid non-empty quantities remain unresolved. The summary reports recognized and unresolved rows.

Click any results table header to sort; click again to reverse the order. Currency sorting uses exact amounts rather than rounded k/m/b labels. Columns with multiple values are compared from left to right; missing values form a separate group. Sorting is preserved on refresh and language changes.

Blueprints show **Avg cost / 1 BPC** and **Avg profit / 1 BPC** beside stack totals. One copy includes the configured number of runs. These averages are stack totals divided by the number of copies; a separate one-copy analysis can differ because market depth and liquidity depend on quantity.

## Valuation rules

- Sell orders and material purchases use Jita 4-4, station `60003760`, system `30000142`. History is for **The Forge region**, `10000002`, as a proxy for Jita liquidity.
- Instant Sell walks eligible buy orders, respecting remaining volume, minimum volume and stargate range. Unsold quantities are shown explicitly.
- Amounts use decimal arithmetic; snapshots preserve decimals as text without converting them to floating-point numbers. Missing scenarios show N/A. Partial totals include known components and are marked. Unsold quantities contribute no instant-sale proceeds.
- Missing history days contribute zero volume, but no invented price. Confidence reflects missing observations. Realistic value blends sale scenarios and requires the relevant prices.
- Manufacturing material efficiency applies to the whole job, without structure rigs. A CANNOT BUILD status preserves the economic calculation while identifying unmet skill requirements. Unprofitable copies have zero build value because the value is capped at a minimum of zero.
- Realistic value, confidence, liquidity and sale time are transparent estimates, not guaranteed sale proceeds. Details show their inputs and score components.
- Blueprint economics assume a complete independent purchase of materials. Materials in your loot never reduce the manufacturing cost.
- Manufacturing uses Jita NPC station fees and live ESI cost indices / adjusted prices. Blueprint build value is potential positive manufacturing profit, not a contract price for the copy. Additional production capital and required skills are needed.
- Per-copy figures are averages across the analyzed stack. Manufacturing time is per copy/job.
- The mechanics baseline is the supplied specification dated 2026-09-09. Constants are in `app/rules.py`. The ESI compatibility date is capped at the current UTC−11 calendar day to avoid future-date rejection.

## Watchlist and sessions

Watchlist targets are per unit. Choose sell price, buy price or realistic net, and either `>=` or `<=`. Changing the mode resets measurements so different metrics are not compared. Refresh respects ESI cache expiry. Targets accept English `1,234.56` or Polish `1 234,56` according to the selected language.

Sessions preserve immutable valuation snapshots. Filter by activity and local date. Statistics include mean/median value, best/worst activity, ISK/hour for timed sessions, per-pilot values and observed drop frequencies. These are personal observations, not official drop probabilities. Historical value includes regular-item realistic value plus potential blueprint manufacturing value; it is not a record of realized sales. ISK/hour excludes manufacturing and sale waiting time.

## Optional EVE SSO

Manual mode works without SSO. To connect a character, register a Native / PKCE application in the EVE developer portal and enter its public **Client ID** in settings.

- Callback: `http://localhost:8765/callback`
- Scopes: `esi-skills.read_skills.v1` and `esi-characters.read_standings.v1`
- Client Secret is not used. Refresh tokens are kept in Windows Credential Manager; access tokens remain in memory.
- JWT signatures, issuer, audience, client ID and OAuth state are checked. A 60-second clock tolerance accommodates small differences between Windows and SSO time.
- If a larger clock difference is reported, use Windows **Settings → Time & language → Date & time → Sync now**, then reconnect.
- Skills and raw standings are imported; manual override preserves your manual values. Set clone state and blueprint parameters manually.
- Port 8765 must be free. Login times out after three minutes. Synchronization runs every 15 minutes while the app is open; there is no separate background service.

Integration documentation: [CCP Static Data](https://developers.eveonline.com/docs/services/static-data/) and [CCP SSO / PKCE](https://developers.eveonline.com/docs/services/sso/).

## Local data and maintenance

The app stores SQLite, cached market data and rotating logs in `%LOCALAPPDATA%\EveLootAnalyzer`. Open or back up this folder from **Data**. Set `EVE_LOOT_DATA` to use a separate directory. JSON exports exclude tokens.

A bundled SDE index is included. Use **Data → Check / download SDE** for updates. Public market errors fall back to cached data when available and mark it stale; missing data never becomes an invented price.

## Tests and Windows build

```powershell
python -m pip install pytest pyinstaller
python -m pytest tests -q
powershell -ExecutionPolicy Bypass -File build.ps1
```

The build script runs the tests and creates the EXE folder and portable ZIP under `dist-v1.5`.

To build the single-file installer, install Inno Setup 6 and run:

```powershell
powershell -ExecutionPolicy Bypass -File build-installer.ps1
```

If the compiler is in a custom location, pass `-Compiler "C:\path\to\ISCC.exe"`. The script creates `dist-v1.5/EveLootAnalyzer-Setup-1.5.exe` and its SHA-256 checksum. Upload these two files as assets of a GitHub release; users only need the EXE.

The domain modules are `parser.py`, `market.py`, `industry.py` and `rules.py`. Integrations are in `esi.py`, `sde.py` and `sso.py`; `storage.py` manages SQLite, `engine.py` coordinates analysis, and `ui.py` contains the PySide6 interface. Network requests and SDE imports run outside the GUI thread. Localization catalogs are in `app/translations.py`; Qt Polish translations are bundled in `assets/qt`.

## Validation and limitations

The tests cover calculations, parser formats, market depth, caching, profiles, snapshots, watchlist, sorting, per-copy values and language changes during analysis. Public ESI/SDE integration and packaged startup have been checked locally. Full character login requires your Client ID and authorization. No separate clean-machine certification or Authenticode signature is provided.

EVE Online and associated names belong to CCP. This is an independent external calculator.
