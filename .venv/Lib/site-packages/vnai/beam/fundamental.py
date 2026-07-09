"""
Fundamental financial reports with tier-based period limiting.
Provides unified interface for financial reports from multiple sources (VCI, KBS, TCBS)
with automatic tier-based period limiting:
- Guest tier: 4 periods max
- Free tier: 8 periods max
- Paid tier: Unlimited
Applies limits intelligently based on data structure:
- VCI/KBS: Periods in columns (slice columns)
- TCBS: Periods in index (slice rows)
"""
import pandas as pd
from typing import Optional
from vnai.beam.auth import authenticator
PERIOD_LIMITS = {
'guest': 4,
'free': 8,
'bronze': None,
'silver': None,
'golden': None,
}

def get_max_periods() -> Optional[int]:
    tier = authenticator.get_tier()
    return PERIOD_LIMITS.get(tier)

def parse_period(period_str: str) -> tuple:
    if isinstance(period_str, str):
        if'-Q' in period_str:
            year, quarter = period_str.split('-Q')
            return (int(year), int(quarter))
        elif period_str.isdigit():
            return (int(period_str), 5)
    return (0, 0)

def limit_periods_by_columns(df: pd.DataFrame, max_periods: Optional[int] = None) -> pd.DataFrame:
    if max_periods is None:
        return df
    metadata_cols = [
'ticker','yearReport','lengthReport',
'item','item_en','item_id','unit','levels','row_number'
    ]
    period_cols = []
    for col in df.columns:
        if isinstance(col, str) and col not in metadata_cols:
            if col.isdigit() or (len(col) > 4 and'-Q' in col):
                period_cols.append(col)
    if not period_cols:
        return df
    period_cols_sorted = sorted(period_cols, key=parse_period, reverse=True)
    keep_periods = period_cols_sorted[:max_periods]
    metadata_cols_present = [col for col in metadata_cols if col in df.columns]
    financial_cols = [col for col in df.columns if col not in metadata_cols and col not in period_cols]
    final_cols = metadata_cols_present + financial_cols + keep_periods
    return df[final_cols]

def limit_periods_by_index(df: pd.DataFrame, max_periods: Optional[int] = None) -> pd.DataFrame:
    if max_periods is None:
        return df
    periods = df.index.tolist()
    periods_sorted = sorted(periods, key=parse_period, reverse=True)
    keep_periods = periods_sorted[:max_periods]
    return df.loc[keep_periods]

def limit_vci_periods(df: pd.DataFrame, max_periods: Optional[int] = None) -> pd.DataFrame:
    if max_periods is None or df.empty:
        return df
    period_cols = []
    for col in df.columns:
        if isinstance(col, str) and (col.isdigit() or (len(col) > 4 and'-Q' in col)):
            if col not in ['row_number','item_id']:
                period_cols.append(col)
    if period_cols:
        return limit_periods_by_columns(df, max_periods=max_periods)
    if'yearReport' in df.columns:
        sort_cols = ['yearReport']
        if'lengthReport' in df.columns:
            sort_cols.append('lengthReport')
        df_sorted = df.sort_values(by=sort_cols, ascending=False)
        df_limited = df_sorted.head(max_periods).copy()
        df_limited = df_limited.reset_index(drop=True)
        return df_limited
    return df

def apply_period_limit(df: pd.DataFrame, by_index: bool = False, source: str ='default') -> pd.DataFrame:
    max_periods = get_max_periods()
    if source =='vci' and'yearReport' in df.columns:
        return limit_vci_periods(df, max_periods)
    elif by_index:
        return limit_periods_by_index(df, max_periods)
    else:
        return limit_periods_by_columns(df, max_periods)

class FinancialReports:
    def __init__(self, symbol: str, source: str ='vci', show_log: bool = False):
        self.symbol = symbol
        self.source = source.lower()
        self.show_log = show_log
        if self.source =='vci':
            from vnstock.explorer.vci import Finance as VCI_Finance
            self.finance = VCI_Finance(symbol=symbol, show_log=show_log)
            self.by_index = False
        elif self.source =='kbs':
            from vnstock.explorer.kbs import Finance as KBS_Finance
            self.finance = KBS_Finance(symbol=symbol, show_log=show_log)
            self.by_index = False
        elif self.source =='tcbs':
            from vnstock.explorer.tcbs import Finance as TCBS_Finance
            self.finance = TCBS_Finance(symbol=symbol, show_log=show_log)
            self.by_index = True
        else:
            raise ValueError(f"Unsupported source: {source}. Must be 'vci', 'kbs', or 'tcbs'.")

    def balance_sheet(self, period: str ='year', lang: Optional[str] ='en',
                     show_log: Optional[bool] = False) -> pd.DataFrame:
        if self.source =='vci':
            fetch_limit = 100
            df = self.finance._get_financial_report('balance_sheet', period=period, lang=lang,
                                                   show_log=show_log, limit=fetch_limit)
        elif self.source =='kbs':
            df = self.finance.balance_sheet(period=period, show_log=show_log)
        elif self.source =='tcbs':
            df = self.finance.balance_sheet(period=period, show_log=show_log)
        df = apply_period_limit(df, by_index=self.by_index, source=self.source)
        if not hasattr(self,'_notice_shown'):
            self._notice_shown = False
        if not self._notice_shown:
            from vnai.beam.patching import should_show_notice, display_period_limit_notice_jupyter
            if should_show_notice():
                self._notice_shown = True
                display_period_limit_notice_jupyter()
        return df

    def income_statement(self, period: str ='year', lang: Optional[str] ='en',
                        show_log: Optional[bool] = False) -> pd.DataFrame:
        if self.source =='vci':
            fetch_limit = 100
            df = self.finance._get_financial_report('income_statement', period=period, lang=lang,
                                                   show_log=show_log, limit=fetch_limit)
        elif self.source =='kbs':
            df = self.finance.income_statement(period=period, show_log=show_log)
        elif self.source =='tcbs':
            df = self.finance.income_statement(period=period, show_log=show_log)
        df = apply_period_limit(df, by_index=self.by_index, source=self.source)
        if not hasattr(self,'_notice_shown'):
            self._notice_shown = False
        if not self._notice_shown:
            from vnai.beam.patching import should_show_notice, display_period_limit_notice_jupyter
            if should_show_notice():
                self._notice_shown = True
                display_period_limit_notice_jupyter()
        return df

    def cash_flow(self, period: str ='year', lang: Optional[str] ='en',
                 show_log: Optional[bool] = False) -> pd.DataFrame:
        if self.source =='vci':
            fetch_limit = 100
            df = self.finance._get_financial_report('cash_flow', period=period, lang=lang,
                                                   show_log=show_log, limit=fetch_limit)
        elif self.source =='kbs':
            df = self.finance.cash_flow(period=period, show_log=show_log)
        elif self.source =='tcbs':
            df = self.finance.cash_flow(period=period, show_log=show_log)
        df = apply_period_limit(df, by_index=self.by_index, source=self.source)
        if not hasattr(self,'_notice_shown'):
            self._notice_shown = False
        if not self._notice_shown:
            from vnai.beam.patching import should_show_notice, display_period_limit_notice_jupyter
            if should_show_notice():
                self._notice_shown = True
                display_period_limit_notice_jupyter()
        return df

def balance_sheet(symbol: str, source: str ='vci', period: str ='year',
                 lang: Optional[str] ='en', show_log: bool = False) -> pd.DataFrame:
    reports = FinancialReports(symbol=symbol, source=source, show_log=show_log)
    return reports.balance_sheet(period=period, lang=lang, show_log=show_log)

def income_statement(symbol: str, source: str ='vci', period: str ='year',
                    lang: Optional[str] ='en', show_log: bool = False) -> pd.DataFrame:
    reports = FinancialReports(symbol=symbol, source=source, show_log=show_log)
    return reports.income_statement(period=period, lang=lang, show_log=show_log)

def cash_flow(symbol: str, source: str ='vci', period: str ='year',
             lang: Optional[str] ='en', show_log: bool = False) -> pd.DataFrame:
    reports = FinancialReports(symbol=symbol, source=source, show_log=show_log)
    return reports.cash_flow(period=period, lang=lang, show_log=show_log)