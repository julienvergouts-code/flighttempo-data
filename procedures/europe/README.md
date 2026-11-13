# European procedure data status

## Current position

There is **no complete, free, publicly redistributable Europe-wide SID/STAR/approach dataset** included in FlightTempo at this time. Do not treat the FAA procedure files in this repository as European coverage.

EUROCONTROL's European AIS Database (EAD) is the right starting point for authoritative European AIP material. EAD Basic offers registered users free access to a limited set of aeronautical information for general purposes. It is not a live operational database or an automatically redistributable, pan-European CSV feed. EAD distribution services and national AIS publications have their own access and licensing conditions; each source must be checked before extraction or redistribution.

Useful starting points:

- [EUROCONTROL European AIS Database (EAD)](https://www.eurocontrol.int/service/european-ais-database-ead)
- [EAD Basic](https://www.eurocontrol.int/service/ead-basic)
- [EUROCONTROL terms of use](https://www.eurocontrol.int/terms-use)

## Community / simulator data reviewed

These can help identify possible test material, but they are not a replacement for a current, complete European AIP database:

- [FlightGear procedures community repository](https://github.com/arneatec/flightgear-procedures) contains a small Bulgaria sample (Sofia and Burgas files in the current tree). Its README warns that procedures may not represent current procedures and limits intended use to recreational/educational simulator purposes. The repository contains a CC0 declaration, but the underlying chart-derived source and current validity still need airport-by-airport review before importing into FlightTempo.
- [FlightGear TerraSync](https://github.com/terrasync/main) contains a few isolated European procedure XML files, including Brest and Ponta Delgada. The inspected records carry a 2016 build note and the repository does not declare a machine-readable data licence. They are not imported.
- [Geneva FlightGear scenery](https://github.com/FGMEMBERS-SCENERY/LSGG-fg-CustomScenery) includes a Geneva procedures file with a GPL-2.0-or-later notice and 2015 copyright. It is a single-airport simulator sample, not current pan-European data. It is not imported.

## Import gate for European sources

A national or community procedure source must not be enabled in the main manifest until all of the following are recorded and checked:

1. Provider, exact source URL and retrieval date.
2. Explicit licence and permission to redistribute the extracted data in a public repository and in a commercial app where applicable.
3. AIRAC or source cycle, effective date and expiry date (or an explicit statement that the cycle is unknown).
4. Airport/country coverage and the actual record counts.
5. Procedure identifiers, runway/transition associations, ordered legs, path terminators, altitude/speed constraints and fix references retained without synthetic geometry.
6. File checksums and automated schema/coordinate/leg-sequence validation.

Do not copy proprietary MSFS/Navblue or paid navdata into this public repository without explicit redistribution permission. A database being installed with a simulator does not make it open data.

**Until a source passes this gate, European procedures remain unavailable in FlightTempo.** The app may use clearly labelled non-procedure fallback routing, but must not fabricate SID, STAR or approach legs from runway headings, airway tracks or generic airport geometry.
