# ADS-B route learning evidence

This subsystem turns a **single-aircraft readsb trace JSON** into evidence linking
observed ADS-B positions to existing navigation fixes.

## Run locally

```bash
python scripts/adsb_learning/match_trace.py --trace trace.json
```

## GitHub Actions

Run **Learn navigation evidence from ADS-B trace** manually and supply a direct
download URL for one aircraft's trace JSON. The workflow downloads only that
trace, matches positions to the existing waypoint reference, and commits
versioned evidence under this directory.

The whole-sky ADSB.lol daily archive is multi-gigabyte and split across assets.
This workflow deliberately does not download that archive on a schedule. A
separate, efficient per-aircraft historical trace endpoint/source must be
confirmed before enabling unattended daily ingestion.

## Data integrity

- ADS-B proximity is not proof of exact fix crossing, filed route, airway clearance,
  or procedure usage.
- Matches are evidence only; they do not alter authoritative fixes or airway graph.
- Multiple independent flights can accumulate evidence in `fix_evidence.json`.
- ADSB.lol data is ODbL 1.0. Preserve attribution and assess share-alike duties
  before redistributing derived databases.
- Never place confidential airline OFPs in this public repository.
