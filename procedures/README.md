# FlightTempo Procedures Data

This directory is reserved for genuine terminal procedure datasets.

- `sids/`: Standard Instrument Departure procedures.
- `stars/`: Standard Terminal Arrival procedures.
- `approaches/`: Published ILS and RNAV/RNP approach procedures.
- `source_data/`: Original, redistributable source files used to build the normalized procedure datasets.

## Inclusion rules

- Include only procedures supported by authentic source records.
- Retain the procedure identifier, airport, runway/transition applicability, ordered legs, constraints, source and provenance.
- Do not construct SID, STAR or approach legs from runway headings, airport locations, VOR positions or guessed geometry.
- Do not treat a localizer facility record alone as a complete published ILS approach.
- LOC-only approaches are outside the current display scope.
- If no suitable ILS or RNAV/RNP procedure is available, the app may draw a simplified direct airport/runway connection, explicitly labelled as a visual fallback rather than a published procedure.

## Source and cycle

The selected expansion source ecosystem is FlightGear navigation data. A procedure dataset is not eligible for publication until its actual upstream origin, redistribution licence, release/cycle (if explicitly supplied), parser and semantic validation have been verified.

Do not ingest FAA CIFP, commercial navdata exports or other replacement sources unless the project source decision is explicitly changed. Never infer or manufacture an AIRAC cycle.
