"""Sample analyses: final data, trade balance, bilateral mirror data."""

import logging
from typing import Optional

import pandas as pd

import comtradeapicall

from .api_utils import export_dataframe_to_csv, safe_api_call
from .config import get_api_key, get_output_dir

logger = logging.getLogger("comtrade_pipeline")


def _save(df: Optional[pd.DataFrame], name: str, label: str, columns=None) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        logger.warning("⚠️ ไม่พบข้อมูล %s", label)
        return None
    export_dataframe_to_csv(df, get_output_dir() / name, columns)
    return df


def run_final_data_sample(reporter_code: str = "842", cmd_code: str = "8703", period: str = "2022",
                          api_key: Optional[str] = None) -> Optional[pd.DataFrame]:
    """Final Data: HS6-standardised imports of one reporter."""
    df = safe_api_call(
        comtradeapicall.getFinalData,
        subscription_key=get_api_key(api_key), typeCode="C", freqCode="A", clCode="HS", period=str(period),
        reporterCode=str(reporter_code), cmdCode=str(cmd_code), flowCode="M", partnerCode=None,
        partner2Code=None, customsCode=None, motCode=None, maxRecords=5000, format_output="JSON",
        aggregateBy=None, breakdownMode="classic", countOnly=None, includeDesc=True,
    )
    return _save(df, f"final_data_{cmd_code}_{reporter_code}.csv", "Final Data",
                 ["reporterDesc", "partnerDesc", "cmdCode", "cmdDesc", "primaryValue", "netWgt"])


def run_trade_balance_sample(reporter_code: str = "764", period: str = "2022", cmd_code: str = "TOTAL",
                             api_key: Optional[str] = None) -> Optional[pd.DataFrame]:
    """Trade balance (exports - imports)."""
    df = safe_api_call(
        comtradeapicall.getTradeBalance,
        subscription_key=get_api_key(api_key), typeCode="C", freqCode="A", clCode="HS", period=str(period),
        reporterCode=str(reporter_code), cmdCode=str(cmd_code), partnerCode=None,
    )
    return _save(df, f"trade_balance_{reporter_code}_{period}.csv", "Trade Balance")


def run_bilateral_mirror_sample(reporter_code: str = "764", partner_code: str = "842", cmd_code: str = "85",
                                flow_code: str = "X", period: str = "2022",
                                api_key: Optional[str] = None) -> Optional[pd.DataFrame]:
    """Bilateral data for comparing reporter vs mirror values."""
    df = safe_api_call(
        comtradeapicall.getBilateralData,
        subscription_key=get_api_key(api_key), typeCode="C", freqCode="A", clCode="HS", period=str(period),
        reporterCode=str(reporter_code), cmdCode=str(cmd_code), flowCode=flow_code, partnerCode=str(partner_code),
    )
    return _save(df, f"bilateral_mirror_{reporter_code}_{partner_code}.csv", "Bilateral")


def run_all_samples(api_key: Optional[str] = None) -> None:
    run_final_data_sample(api_key=api_key)
    run_trade_balance_sample(api_key=api_key)
    run_bilateral_mirror_sample(api_key=api_key)

