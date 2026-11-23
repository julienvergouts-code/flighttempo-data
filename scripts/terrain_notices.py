"""Copernicus DEM GLO-30 notices required by the COPDEM-30 licence (Art. 6a-c).

Single source of truth: the registration scripts rewrite these into the published
indexes, so wording can never drift from what the licence asks for.
"""
ATTRIBUTION = ("© DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under "
               "COPERNICUS by the European Union and ESA; all rights reserved. "
               "Produced using Copernicus WorldDEM-30.")
DISCLAIMER = ("The organisations in charge of the Copernicus programme by law or by delegation do not incur any "
              "liability for any use of the Copernicus WorldDEM-30.")
FIELDS = {"attribution": ATTRIBUTION, "disclaimer": DISCLAIMER}


def refresh(index: dict) -> bool:
    """Overwrite notice fields in ``index``; return True if anything changed."""
    changed = False
    for key, value in FIELDS.items():
        if index.get(key) != value:
            index[key] = value
            changed = True
    return changed
