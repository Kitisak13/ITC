from datetime import datetime, timezone
import json
import pandas as pd
import pytest

from comtrade_pipeline import gdrive_sync, live_updates
from comtrade_pipeline.cli import main as cli_main
from comtrade_pipeline.config import ConfigError


def test_prepare_master_outputs_handles_mixed_str_int_and_parquet(tmp_path):
    """Reproduces and guards against ArrowTypeError when merging CSV strings with API integers."""
    existing_csv = pd.DataFrame(
        [
            {
                "period": "202601",
                "reporterCode": "36",
                "reporterDesc": "Australia",
                "partnerCode": "0",
                "partnerDesc": "World",
                "cmdCode": "100630",
                "cmdDesc": "Semi-milled or wholly milled rice",
                "flowCode": "M",
                "flowDesc": "Import",
                "primaryValue": "100.0",
                "netWgt": "50.0",
                "qty": "50.0",
                "qtyUnitAbbr": "kg",
            }
        ],
        dtype=str,
    )

    api_df = pd.DataFrame(
        [
            {
                "period": 202601,
                "reporterCode": 36,
                "reporterDesc": "Australia",
                "partnerCode": 0,
                "partnerDesc": "World",
                "cmdCode": 100630,
                "cmdDesc": "Semi-milled or wholly milled rice",
                "flowCode": "M",
                "flowDesc": "Import",
                "primaryValue": 250.5,
                "netWgt": 120.0,
                "qty": 120.0,
                "qtyUnitAbbr": "kg",
            },
            {
                "period": 202602,
                "reporterCode": 36,
                "reporterDesc": "Australia",
                "partnerCode": 764,
                "partnerDesc": "Thailand",
                "cmdCode": 100630,
                "cmdDesc": "Semi-milled or wholly milled rice",
                "flowCode": "M",
                "flowDesc": "Import",
                "primaryValue": 500.0,
                "netWgt": 250.0,
                "qty": 250.0,
                "qtyUnitAbbr": None,
            },
        ]
    )

    csv_path = tmp_path / "master_rice_import.csv"
    pq_path = tmp_path / "master_rice_import.parquet"

    combined, added = gdrive_sync._prepare_master_outputs(
        existing_df=existing_csv,
        new_dfs=[api_df],
        csv_path=csv_path,
        parquet_path=pq_path,
        write_parquet=True,
        flow_label="Import",
    )

    # Row 202601 should be deduplicated and updated to 250.5, plus new 202602 row -> total 2 rows (+1)
    assert len(combined) == 2
    assert added == 1
    assert combined.loc[combined["period"] == "202601", "primaryValue"].iloc[0] == 250.5
    assert csv_path.is_file()
    assert pq_path.is_file()

    pq_back = pd.read_parquet(pq_path)
    assert len(pq_back) == 2
    assert list(pq_back["reporterCode"]) == ["36", "36"]


def test_determine_target_years_dynamic():
    nov_2026 = datetime(2026, 11, 16, tzinfo=timezone.utc)
    jan_2027 = datetime(2027, 1, 10, tzinfo=timezone.utc)

    assert gdrive_sync._determine_target_years({"code": "764"}, now_utc=nov_2026) == [2026]
    assert gdrive_sync._determine_target_years({"code": "764"}, now_utc=jan_2027) == [2026, 2027]
    assert gdrive_sync._determine_target_years({"code": "764", "years": [2020, 2025, 2026]}, now_utc=nov_2026) == [
        2025,
        2026,
    ]


def test_gdrive_sync_missing_ids_fails_loudly(monkeypatch):
    monkeypatch.delenv("GDRIVE_IMPORT_CSV_ID", raising=False)
    monkeypatch.delenv("GDRIVE_EXPORT_CSV_ID", raising=False)

    with pytest.raises(ConfigError):
        gdrive_sync.run_gdrive_sync(days_back=7)

    assert cli_main(["gdrive-sync"]) == 1


def test_gdrive_sync_skips_already_synced_releases(monkeypatch, tmp_path):
    state_file = tmp_path / "sync_state.json"
    state_file.write_text(
        json.dumps(
            {
                "last_sync_time": "2026-11-16 01:00:00 UTC",
                "last_updated_countries": ["Australia"],
                "country_releases": {"36": "2026-11-15T12:00:00+00:00"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(gdrive_sync, "STATE_FILE", state_file)
    monkeypatch.setenv("GDRIVE_IMPORT_CSV_ID", "imp-id")
    monkeypatch.setenv("GDRIVE_EXPORT_CSV_ID", "exp-id")
    monkeypatch.setattr(gdrive_sync, "get_gdrive_service", lambda: object())
    monkeypatch.setattr(
        gdrive_sync,
        "get_recently_updated_reporters",
        lambda days_back=7, api_key=None: [
            {"code": "36", "name": "Australia", "release_token": "2026-11-15T12:00:00+00:00"}
        ],
    )

    called = {"fetch": 0}
    monkeypatch.setattr(
        gdrive_sync,
        "fetch_country_rice_flow",
        lambda *a, **kw: called.__setitem__("fetch", called["fetch"] + 1),
    )

    gdrive_sync.run_gdrive_sync(days_back=7, force=False)
    assert called["fetch"] == 0


def test_gdrive_sync_partial_failure_only_records_succeeded_country(monkeypatch, tmp_path):
    state_file = tmp_path / "sync_state.json"
    monkeypatch.setattr(gdrive_sync, "STATE_FILE", state_file)
    monkeypatch.setenv("COMTRADE_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("GDRIVE_IMPORT_CSV_ID", "imp-id")
    monkeypatch.setenv("GDRIVE_EXPORT_CSV_ID", "exp-id")
    monkeypatch.setenv("GDRIVE_IMPORT_PARQUET_ID", "imp-pq-id")
    monkeypatch.setenv("GDRIVE_EXPORT_PARQUET_ID", "exp-pq-id")

    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    base_df = pd.DataFrame(
        [
            {
                "period": "202601",
                "reporterCode": "764",
                "reporterDesc": "Thailand",
                "partnerCode": "0",
                "partnerDesc": "World",
                "cmdCode": "100630",
                "cmdDesc": "Milled rice",
                "flowCode": "M",
                "flowDesc": "Import",
                "primaryValue": "10",
                "netWgt": "5",
                "qty": "5",
                "qtyUnitAbbr": "kg",
            }
        ]
    )
    base_df.to_csv(out_dir / "master_rice_import.csv", index=False, encoding="utf-8-sig")
    base_df.assign(flowCode="X", flowDesc="Export").to_csv(
        out_dir / "master_rice_export.csv", index=False, encoding="utf-8-sig"
    )

    monkeypatch.setattr(gdrive_sync, "get_gdrive_service", lambda: object())
    monkeypatch.setattr(
        gdrive_sync,
        "get_recently_updated_reporters",
        lambda days_back=7, api_key=None: [
            {"code": "36", "name": "Australia", "release_token": "2026-11-16T01:00:00+00:00"},
            {"code": "276", "name": "Germany", "release_token": "2026-11-16T02:00:00+00:00"},
        ],
    )

    def fake_fetch(country_code, country_name, flow_code, years, quota_tracker, **kwargs):
        if country_code == "276":
            raise RuntimeError("transient 502 error")
        return pd.DataFrame(
            [
                {
                    "period": 202602,
                    "reporterCode": int(country_code),
                    "reporterDesc": country_name,
                    "partnerCode": 0,
                    "partnerDesc": "World",
                    "cmdCode": 100630,
                    "cmdDesc": "Milled rice",
                    "flowCode": flow_code,
                    "flowDesc": "Import" if flow_code == "M" else "Export",
                    "primaryValue": 100.0,
                    "netWgt": 50.0,
                    "qty": 50.0,
                    "qtyUnitAbbr": "kg",
                }
            ]
        )

    uploaded = []
    monkeypatch.setattr(gdrive_sync, "fetch_country_rice_flow", fake_fetch)
    monkeypatch.setattr(
        gdrive_sync,
        "upload_update_gdrive_file",
        lambda service, file_id, source_path, mime_type="text/csv": uploaded.append((file_id, source_path.name)),
    )

    gdrive_sync.run_gdrive_sync(days_back=7, force=False)

    saved_state = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved_state["last_updated_countries"] == ["Australia"]
    assert "36" in saved_state["country_releases"]
    assert "276" not in saved_state["country_releases"]
    assert {fid for fid, _ in uploaded} == {"imp-id", "imp-pq-id", "exp-id", "exp-pq-id"}


def test_get_recently_updated_reporters_utc_dates(monkeypatch):
    recent_iso = pd.Timestamp.now(timezone.utc).isoformat()
    old_iso = (pd.Timestamp.now(timezone.utc) - pd.Timedelta(days=20)).isoformat()

    mock_df = pd.DataFrame(
        [
            {"reporterCode": "764", "typeCode": "C", "publicationDate": recent_iso, "period": "202609"},
            {"reporterCode": "842", "typeCode": "C", "publicationDate": old_iso, "period": "202608"},
            {"reporterCode": "704", "typeCode": "S", "publicationDate": recent_iso, "period": "202609"},
        ]
    )
    monkeypatch.setattr(live_updates, "fetch_comtrade_releases", lambda api_key=None: mock_df)

    res = live_updates.get_recently_updated_reporters(days_back=7)
    assert len(res) == 1
    assert res[0]["code"] == "764"
    assert res[0]["release_token"]
    assert res[0]["years"] == [2026]


def test_get_recently_updated_reporters_fallback_release_token(monkeypatch):
    mock_df = pd.DataFrame(
        [
            {"reporterCode": "36", "typeCode": "C", "period": "202609", "datasetCode": "30036202609"},
        ]
    )
    monkeypatch.setattr(live_updates, "fetch_comtrade_releases", lambda api_key=None: mock_df)

    res = live_updates.get_recently_updated_reporters(days_back=7)
    assert len(res) == 1
    assert res[0]["code"] == "36"
    assert res[0]["release_token"] == "datasetCode:30036202609"
