import pytest
import pandas as pd
from comtrade_pipeline.country_resolver import resolve_country, resolve_countries
from comtrade_pipeline.rice_benchmark import clean_unit_values, run_rice_benchmark


def test_resolve_country_iso3():
    c = resolve_country("THA")
    assert c is not None
    code, name = c
    assert code == "764"
    assert "Thailand" in name

    c_usa = resolve_country("USA")
    assert c_usa is not None
    assert c_usa[0] == "842"

    c_vnm = resolve_country("vnm")
    assert c_vnm is not None
    assert c_vnm[0] == "704"


def test_resolve_country_numeric():
    c = resolve_country("764")
    assert c is not None
    assert c[0] == "764"
    assert "Thailand" in c[1]

    # Unknown code returns None
    assert resolve_country("999999") is None


def test_resolve_countries_list():
    res = resolve_countries(["THA", "VNM", "USA"])
    assert len(res) == 3
    codes = [item["code"] for item in res]
    assert "764" in codes
    assert "704" in codes
    assert "842" in codes


def test_clean_unit_values():
    # DataFrame with valid numbers and one crazy outlier
    df = pd.DataFrame({
        "primaryValue": [1000.0, 1050.0, 1100.0, 950.0, 1020.0, 1000000.0],
        "netWgt": [1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1.0],  # 1 million per kg
    })
    cleaned = clean_unit_values(df)
    assert len(cleaned) < len(df)
    assert "unit_price_usd_kg" in cleaned.columns
    assert "unit_price_usd_ton" in cleaned.columns
    # Outlier should be eliminated
    assert cleaned["unit_price_usd_kg"].max() < 100.0


def test_rice_benchmark_from_cache():
    # Run benchmark on existing output files
    df = run_rice_benchmark(
        countries=["THA", "USA"],
        flow="Export",
        year=2024
    )
    if not df.empty:
        assert "Country" in df.columns
        assert "Avg_Price_USD_per_Ton" in df.columns
