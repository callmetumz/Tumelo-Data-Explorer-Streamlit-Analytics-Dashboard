"""A built-in demo dataset.

The data is synthetic retail sales for a South African shop. It is
deliberately messy - missing values, repeated rows, stray whitespace - so
every feature of the app has something to show without needing an upload.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SAMPLE_NAME = "Sample retail sales"

REGIONS = ["Western Cape", "Gauteng", "KwaZulu-Natal", "Eastern Cape", "Free State"]
REGION_WEIGHTS = [0.28, 0.34, 0.2, 0.11, 0.07]

#: category -> (typical unit price in rand, relative popularity)
CATEGORIES = {
    "Electronics": (2400.0, 0.18),
    "Groceries": (85.0, 0.34),
    "Clothing": (420.0, 0.22),
    "Home & Garden": (650.0, 0.14),
    "Books": (210.0, 0.12),
}
PAYMENT_METHODS = ["Card", "EFT", "Cash", "Mobile wallet"]


def make_sample_dataset(rows: int = 1200, seed: int = 42) -> pd.DataFrame:
    """Generate the demo dataset. The same seed always gives the same data."""
    rng = np.random.default_rng(seed)

    categories = list(CATEGORIES)
    popularity = np.array([CATEGORIES[c][1] for c in categories])
    category = rng.choice(categories, size=rows, p=popularity / popularity.sum())
    base_price = np.array([CATEGORIES[c][0] for c in category])

    day_of_year = rng.integers(0, 365, size=rows)
    order_date = pd.Timestamp("2025-01-01") + pd.to_timedelta(np.sort(day_of_year), unit="D")
    # Sales build up towards the end of the year.
    season = 1 + 0.35 * np.sin((np.sort(day_of_year) - 250) / 365 * 2 * np.pi)

    unit_price = np.round(base_price * rng.lognormal(0, 0.25, size=rows), 2)
    units = np.maximum(1, rng.poisson(2.2 * season, size=rows))
    discount_pct = rng.choice([0, 0, 0, 5, 10, 15, 20], size=rows)
    revenue = np.round(units * unit_price * (1 - discount_pct / 100), 2)
    rating = np.clip(np.round(rng.normal(4.1, 0.7, size=rows), 1), 1, 5)

    df = pd.DataFrame(
        {
            "order_id": [f"ORD-{10000 + i}" for i in range(rows)],
            "order_date": order_date.strftime("%Y-%m-%d"),
            "region": rng.choice(REGIONS, size=rows, p=REGION_WEIGHTS),
            "category": category,
            "payment_method": rng.choice(PAYMENT_METHODS, size=rows, p=[0.5, 0.2, 0.18, 0.12]),
            "units": units,
            "unit_price": unit_price,
            "discount_pct": discount_pct,
            "revenue": revenue,
            "customer_rating": rating,
        }
    )

    # --- make it messy on purpose -----------------------------------------
    def pick(fraction: float) -> np.ndarray:
        return rng.choice(rows, size=int(rows * fraction), replace=False)

    df.loc[pick(0.08), "customer_rating"] = np.nan
    df.loc[pick(0.04), "payment_method"] = None
    df.loc[pick(0.025), "unit_price"] = np.nan
    df.loc[pick(0.015), "region"] = None
    messy = pick(0.03)
    df.loc[messy, "region"] = df.loc[messy, "region"].map(
        lambda value: f"  {value} " if isinstance(value, str) else value
    )

    repeats = df.sample(n=30, random_state=seed)
    df = pd.concat([df, repeats], ignore_index=True)
    return df.sample(frac=1, random_state=seed).reset_index(drop=True)


def sample_csv_bytes() -> bytes:
    """The demo dataset as CSV, for the "download a sample file" button."""
    return make_sample_dataset().to_csv(index=False).encode("utf-8")
