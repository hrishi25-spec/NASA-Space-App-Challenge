"""Curated areas of interest for the mission console.

The sibling Pyro-Harmony repo had one genuinely useful idea here: named fire regions
carrying a biome, a peak season and a list of notable past events, so a demo can walk
an audience through real fire regimes instead of one anonymous bounding box.

In this project the presets are a *view*, never a data source. Choosing one sets the
AOI filter and flies the camera; `POST /demo?region=...` can synthesise a record inside
the preset so the demo works for any of them, and `POST /archive` can pull a real FIRMS
window for the preset when a MAP_KEY is configured. Real uploaded data is untouched.

`bbox` is [minlat, minlon, maxlat, maxlon] -- the convention every endpoint and the
`?bbox=` query string already use (the sibling repo used GeoJSON order; converting once
here keeps the rest of the API consistent).

`firms_region` maps onto the FIRMS 7d/24h area feeds allowlisted in main.py
(LIVE_REGIONS), so the live pull can follow whichever preset is selected.
"""

REGIONS = {
    "california": {
        "name": "California",
        "subtitle": "Western US wildfires",
        "bbox": [32.5, -124.4, 42.0, -114.1],
        "center": [37.2, -119.5],
        "zoom": 5.6,
        "biome": "Temperate forest & chaparral",
        "peak_months": [7, 8, 9, 10],
        "events": [
            {"year": 2018, "note": "Camp Fire"},
            {"year": 2020, "note": "August Complex"},
            {"year": 2021, "note": "Dixie Fire"},
        ],
        "firms_region": "North_and_Central_America",
    },
    "amazon": {
        "name": "Amazon & Pantanal",
        "subtitle": "South America",
        "bbox": [-18.0, -70.0, -3.0, -48.0],
        "center": [-9.5, -58.5],
        "zoom": 4.6,
        "biome": "Tropical rainforest & Cerrado savanna",
        "peak_months": [8, 9, 10],
        "events": [
            {"year": 2019, "note": "Amazon surge"},
            {"year": 2020, "note": "Pantanal record fires"},
            {"year": 2024, "note": "drought fires"},
        ],
        "firms_region": "South_America",
    },
    "australia": {
        "name": "Southeastern Australia",
        "subtitle": "Bushfire country",
        "bbox": [-39.0, 140.0, -28.0, 153.5],
        "center": [-34.5, 147.0],
        "zoom": 5.6,
        "biome": "Eucalyptus temperate & dry forest",
        "peak_months": [11, 12, 1, 2],
        "events": [
            {"year": 2019, "note": "Black Summer begins"},
            {"year": 2020, "note": "Black Summer peak"},
        ],
        "firms_region": "Northern_and_Central_Australia",
    },
    "punjab_crop": {
        "name": "Punjab & Haryana",
        "subtitle": "Agricultural crop residue",
        "bbox": [29.5, 74.2, 32.5, 77.3],
        "center": [30.9, 75.8],
        "zoom": 6.6,
        "biome": "Intensive agricultural cropland",
        "peak_months": [10, 11, 4, 5],
        "events": [
            {"year": 2016, "note": "stubble smog crisis"},
            {"year": 2021, "note": "peak post-harvest residue"},
        ],
        "firms_region": "South_Asia",
    },
    "mediterranean": {
        "name": "Mediterranean basin",
        "subtitle": "Southern Europe",
        "bbox": [36.0, -9.5, 45.0, 28.5],
        "center": [39.5, 15.0],
        "zoom": 4.6,
        "biome": "Mediterranean sclerophyll & pine forest",
        "peak_months": [6, 7, 8, 9],
        "events": [
            {"year": 2021, "note": "Greece & Turkey megafires"},
            {"year": 2023, "note": "Rhodes & Attica blazes"},
        ],
        "firms_region": "Europe",
    },
}


def region_box(key):
    """[minlat, minlon, maxlat, maxlon] for a preset, or None for an unknown key."""
    region = REGIONS.get(key)
    return list(region["bbox"]) if region else None


def region_keys():
    return ", ".join(REGIONS)
