# File: eodhd_finance.py

import os
import requests
import pandas as pd
from datetime import datetime
from typing import Dict, Optional, Union, List, Any
from enum import Enum
from openpyxl.utils import get_column_letter

class StatementType(Enum):
    BALANCE_SHEET = 'Balance_Sheet'
    INCOME_STATEMENT = 'Income_Statement'
    CASH_FLOW = 'Cash_Flow'

class MetricType(Enum):
    """
    Define how to calculate annual metrics:
    SUM - Sum up quarterly values (e.g., Revenue, Net Income)
    LATEST - Use latest quarter value (e.g., Balance Sheet items)
    AVERAGE - Average of quarterly values
    """
    SUM = 'sum'
    LATEST = 'latest'
    AVERAGE = 'average'

class FinancialMetrics:
    # Income Statement Metrics
    INCOME_STATEMENT_METRICS = [
        'totalRevenue', 'costOfRevenue', 'grossProfit', 'operatingIncome',
        'netIncome', 'ebitda', 'depreciationAndAmortization', 'discontinuedOperations',
        'ebit', 'effectOfAccountingCharges', 'extraordinaryItems', 'incomeBeforeTax',
        'incomeTaxExpense', 'interestExpense', 'interestIncome', 'minorityInterest',
        'netIncomeApplicableToCommonShares', 'netIncomeFromContinuingOps',
        'netInterestIncome', 'nonOperatingIncomeNetOther', 'nonRecurring',
        'operatingIncome', 'otherItems', 'otherOperatingExpenses',
        'preferredStockAndOtherAdjustments', 'reconciledDepreciation',
        'researchDevelopment', 'sellingAndMarketingExpenses',
        'sellingGeneralAdministrative', 'taxProvision', 'totalOperatingExpenses',
        'totalOtherIncomeExpenseNet'
    ]

    # Balance Sheet Metrics
    BALANCE_SHEET_METRICS = [
        'accountsPayable', 'accumulatedAmortization', 'accumulatedDepreciation',
        'accumulatedOtherComprehensiveIncome', 'additionalPaidInCapital',
        'capitalLeaseObligations', 'capitalStock', 'capitalSurpluse', 'cash',
        'cashAndEquivalents', 'cashAndShortTermInvestments', 'commonStock',
        'commonStockSharesOutstanding', 'commonStockTotalEquity',
        'currentDeferredRevenue', 'deferredLongTermAssetCharges',
        'deferredLongTermLiab', 'earningAssets', 'goodWill', 'intangibleAssets',
        'inventory', 'liabilitiesAndStockholdersEquity', 'longTermDebt',
        'longTermDebtTotal', 'longTermInvestments', 'negativeGoodwill', 'netDebt',
        'netInvestedCapital', 'netReceivables', 'netTangibleAssets',
        'netWorkingCapital', 'nonCurrentAssetsTotal', 'nonCurrentLiabilitiesOther',
        'nonCurrentLiabilitiesTotal', 'nonCurrrentAssetsOther',
        'noncontrollingInterestInConsolidatedEntity', 'otherAssets',
        'otherCurrentAssets', 'otherCurrentLiab', 'otherLiab',
        'otherStockholderEquity', 'preferredStockRedeemable',
        'preferredStockTotalEquity', 'propertyPlantAndEquipmentGross',
        'propertyPlantAndEquipmentNet', 'propertyPlantEquipment',
        'retainedEarnings', 'retainedEarningsTotalEquity', 'shortLongTermDebt',
        'shortLongTermDebtTotal', 'shortTermDebt', 'shortTermInvestments',
        'temporaryEquityRedeemableNoncontrollingInterests', 'totalAssets',
        'totalCurrentAssets', 'totalCurrentLiabilities', 'totalLiab',
        'totalPermanentEquity', 'totalStockholderEquity', 'treasuryStock',
        'warrants'
    ]

    # Cash Flow Metrics
    CASH_FLOW_METRICS = [
        'beginPeriodCashFlow', 'capitalExpenditures', 'cashAndCashEquivalentsChanges',
        'cashFlowsOtherOperating', 'changeInCash', 'changeInWorkingCapital',
        'changeReceivables', 'changeToAccountReceivables', 'changeToInventory',
        'changeToLiabilities', 'changeToNetincome', 'changeToOperatingActivities',
        'depreciation', 'dividendsPaid', 'endPeriodCashFlow', 'exchangeRateChanges',
        'freeCashFlow', 'investments', 'issuanceOfCapitalStock', 'netBorrowings',
        'netIncome', 'otherCashflowsFromFinancingActivities',
        'otherCashflowsFromInvestingActivities', 'otherNonCashItems',
        'salePurchaseOfStock', 'stockBasedCompensation',
        'totalCashFromFinancingActivities', 'totalCashFromOperatingActivities',
        'totalCashflowsFromInvestingActivities'
    ]
    
class Financials:
    # Metric calculation type mappings
    METRIC_TYPES = {
        StatementType.BALANCE_SHEET: MetricType.LATEST,  # All Balance Sheet metrics use latest value
        StatementType.INCOME_STATEMENT: {  # Income Statement metrics calculations
            'default': MetricType.SUM,  # Default for Income Statement is to sum
            'margin': MetricType.AVERAGE,  # Margins should be averaged
            'ratio': MetricType.AVERAGE
        },
        StatementType.CASH_FLOW: {  # Cash Flow metrics calculations
            'default': MetricType.SUM,  # Default for Cash Flow is to sum
            'endPeriodCashFlow': MetricType.LATEST,
            'beginPeriodCashFlow': MetricType.LATEST
        }
    }

    def __init__(self, symbol: str, api_token: str):
        self.symbol = symbol.upper()
        self._api_token = os.getenv('EODHD_API_KEY')
        self._base_url = 'https://eodhd.com/api'
        self._data = None
        self._quarterly_data = {}
        self._annual_data = {}

    def _fetch_data(self) -> None:
        """Fetch financial data from EODHD API"""
        try:
            url = f'{self._base_url}/fundamentals/{self.symbol}.US'
            params = {
                'api_token': self._api_token,
                'fmt': 'json'
            }
            response = requests.get(url, params=params)
            response.raise_for_status()
            self._data = response.json()
            self._process_all_statements()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching data: {e}")
            self._data = None

    def _process_all_statements(self) -> None:
        """Process all financial statements into quarterly and annual data"""
        if not self._data:
            return

        for statement_type in StatementType:
            try:
                df = pd.DataFrame(self._data)
                financials = df.loc[statement_type.value, 'Financials']
                df_financials = pd.DataFrame(financials)
                
                # Process quarterly data
                quarters_by_year = {}
                for date in df_financials.index:
                    try:
                        quarterly_data = df_financials.loc[date, "quarterly"]
                        if quarterly_data and isinstance(quarterly_data, dict):
                            date_obj = pd.to_datetime(date)
                            year = date_obj.year
                            if year not in quarters_by_year:
                                quarters_by_year[year] = []
                            quarters_by_year[year].append({
                                'date': date_obj,
                                'data': quarterly_data
                            })
                    except Exception as e:
                        print(f"Skipping date {date} for {statement_type.value}: {e}")
                        continue

                # Store quarterly data
                self._quarterly_data[statement_type] = []
                for year in sorted(quarters_by_year.keys(), reverse=True):
                    self._quarterly_data[statement_type].extend(
                        sorted(quarters_by_year[year], key=lambda x: x['date'], reverse=True)
                    )

                print(f"{statement_type.value} Data processed successfully")
                
                # Save to Excel
                self._save_to_excel(
                    f"{self.symbol.lower()}_{statement_type.value.lower()}.xlsx",
                    self._quarterly_data[statement_type]
                )

            except Exception as e:
                print(f"Error processing {statement_type.value}: {e}")

    def _save_to_excel(self, filename: str, data: List[Dict]) -> None:
        """Save financial data to Excel"""
        try:
            if not data:
                return

            # Create DataFrame from the first quarter's data
            metrics = list(data[0]['data'].keys())
            df = pd.DataFrame(index=metrics)

            # Add data for each quarter
            for quarter in data:
                date = quarter['date'].strftime('%Y-%m-%d')
                df[date] = pd.Series({metric: quarter['data'].get(metric) for metric in metrics})

            # Save to Excel
            with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Quarterly')
                
                # Format the worksheet
                worksheet = writer.sheets['Quarterly']
                
                # Adjust column widths
                for idx, col in enumerate(df.columns, start=1):
                    column_letter = get_column_letter(idx + 1)
                    max_length = max(
                        df[col].astype(str).apply(len).max(),
                        len(str(col))
                    )
                    worksheet.column_dimensions[column_letter].width = max_length + 2
                
                # Adjust index column width
                max_index_length = max(len(str(idx)) for idx in df.index)
                worksheet.column_dimensions['A'].width = max_index_length + 2

            print(f"\nExcel file '{filename}' has been created successfully!")
        except Exception as e:
            print(f"Error saving to Excel: {e}")

    def get_metric(self, 
                  statement_type: Union[str, StatementType],
                  metric: str,
                  year: Optional[Union[str, int]] = None,
                  freq: str = 'quarterly') -> Union[float, Dict[str, float], None]:
        """Get specific metric value"""
        if isinstance(statement_type, str):
            statement_type = StatementType(statement_type)
            
        if not self._quarterly_data:
            self._fetch_data()

        if statement_type not in self._quarterly_data:
            return None

        result = {}
        for quarter in self._quarterly_data[statement_type]:
            if metric in quarter['data']:
                result[quarter['date'].strftime('%Y-%m-%d')] = quarter['data'][metric]

        if not result:
            return None

        if year:
            year_str = str(year)
            return {
                date: value 
                for date, value in result.items() 
                if date.startswith(year_str)
            }
        return result

def main():
    api_token = '63f394f93dbbb6.58792646'  # Replace with your API token
    symbol = 'AAPL'
    year = '2024'
    
    # Initialize
    fin = Financials(symbol, api_token)
    
    print(f"\n{'='*50}")
    print(f"Financial Analysis for {symbol} - {year}")
    print(f"{'='*50}")

    # Print all metrics by statement type
    statement_types = {
        'INCOME STATEMENT': (StatementType.INCOME_STATEMENT, FinancialMetrics.INCOME_STATEMENT_METRICS),
        'BALANCE SHEET': (StatementType.BALANCE_SHEET, FinancialMetrics.BALANCE_SHEET_METRICS),
        'CASH FLOW': (StatementType.CASH_FLOW, FinancialMetrics.CASH_FLOW_METRICS)
    }

    for title, (statement_type, metrics) in statement_types.items():
        print(f"\n{title}:")
        print("-" * 50)
        
        for metric in metrics:
            value = fin.get_metric(statement_type, metric, year)
            if value:
                for date, metric_value in value.items():
                    try:
                        if isinstance(metric_value, (int, float)):
                            print(f"{metric.ljust(35)} ({date}): ${float(metric_value):,.2f}")
                        else:
                            print(f"{metric.ljust(35)} ({date}): {metric_value}")
                    except Exception as e:
                        print(f"{metric.ljust(35)} ({date}): Error - {e}")

if __name__ == "__main__":
    main()    