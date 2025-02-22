

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
    METRIC_TYPES = {
        StatementType.BALANCE_SHEET: {
            'default': MetricType.LATEST,  # Default for Balance Sheet is latest value
            'commonStock': MetricType.AVERAGE,  # Common Stock should be averaged
            'commonStockSharesOutstanding': MetricType.AVERAGE  # Shares outstanding should be averaged
        },
        StatementType.INCOME_STATEMENT: {
            'default': MetricType.SUM,  # Default for Income Statement is to sum
            'margin': MetricType.AVERAGE,  # Margins should be averaged
            'ratio': MetricType.AVERAGE
        },
        StatementType.CASH_FLOW: {
            'default': MetricType.SUM,  # Default for Cash Flow is to sum
            'endPeriodCashFlow': MetricType.LATEST,
            'beginPeriodCashFlow': MetricType.LATEST
        }
    }

    def __init__(self, symbol: str, api_token: str):
        self.symbol = symbol.upper()
        self._api_token = api_token
        self._base_url = 'https://eodhd.com/api/fundamentals'
        self._data = None
        self._quarterly_data = {}
        self._annual_data = {}

    def _fetch_data(self) -> None:
        """Fetch financial data from EODHD API"""
        try:
            url = f'{self._base_url}/{self.symbol}?api_token={self._api_token}&fmt=json'
            response = requests.get(url)
            response.raise_for_status()
            self._data = response.json()
            self._process_all_statements()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching data: {e}")
            self._data = None

    def _get_metric_calculation_type(self, statement_type: StatementType, metric: str) -> MetricType:
        """Determine how to calculate annual value for a metric"""
        metric_types = self.METRIC_TYPES[statement_type]

        if isinstance(metric_types, dict):
            # Check for specific metric type
            if metric in metric_types:
                return metric_types[metric]
            # Return default if specified
            if 'default' in metric_types:
                return metric_types['default']

        # If metric_types is not a dict, it's a direct MetricType
        return metric_types

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
                annual_data = {}

                # Calculate annual data by year
                for year in sorted(quarters_by_year.keys(), reverse=True):
                    quarters = sorted(quarters_by_year[year], key=lambda x: x['date'], reverse=True)
                    self._quarterly_data[statement_type].extend(quarters)

                    if len(quarters) == 4:  # Only calculate annual for complete years
                        annual_metrics = {}
                        sample_data = quarters[0]['data']

                        for metric in sample_data.keys():
                            try:
                                calc_type = self._get_metric_calculation_type(statement_type, metric)
                                values = []
                                for q in quarters:
                                    value = q['data'].get(metric)
                                    if value not in ['', None]:
                                        try:
                                            values.append(float(value))
                                        except (ValueError, TypeError):
                                            values.append(0)

                                if values:
                                    if calc_type == MetricType.SUM:
                                        annual_metrics[metric] = sum(values)
                                    elif calc_type == MetricType.AVERAGE:
                                        annual_metrics[metric] = sum(values) / len(values)
                                    elif calc_type == MetricType.LATEST:
                                        annual_metrics[metric] = values[0]
                                else:
                                    annual_metrics[metric] = None

                            except Exception as e:
                                print(f"Error calculating {metric}: {e}")
                                annual_metrics[metric] = None

                        annual_data[year] = annual_metrics

                self._annual_data[statement_type] = annual_data
                print(f"{statement_type.value} Data processed successfully")

                # Save to Excel
                self._save_to_excel(
                    f"{self.symbol.lower()}_{statement_type.value.lower()}.xlsx",
                    self._quarterly_data[statement_type],
                    annual_data
                )

            except Exception as e:
                print(f"Error processing {statement_type.value}: {e}")

    def _save_to_excel(self, filename: str, quarterly_data: List[Dict], annual_data: Dict) -> None:
        """Save financial data to Excel"""
        try:
            if not quarterly_data:
                return

            # Create DataFrame from quarterly data all at once
            metrics = list(quarterly_data[0]['data'].keys())
            data_dict = {}

            # Prepare all data first
            for quarter in quarterly_data:
                date = quarter['date'].strftime('%Y-%m-%d')
                data_dict[date] = {metric: quarter['data'].get(metric) for metric in metrics}

            # Create DataFrame in one go
            df_quarterly = pd.DataFrame(data_dict).T

            # Transpose to get metrics as rows and dates as columns
            df_quarterly = df_quarterly.T

            # Create DataFrame from annual data
            df_annual = pd.DataFrame(annual_data).T if annual_data else None

            # Save to Excel
            with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                df_quarterly.to_excel(writer, sheet_name='Quarterly')
                if df_annual is not None:
                    df_annual.to_excel(writer, sheet_name='Annual')

                # Format worksheets
                for sheet_name in ['Quarterly', 'Annual']:
                    if sheet_name == 'Annual' and df_annual is None:
                        continue

                    worksheet = writer.sheets[sheet_name]
                    df = df_quarterly if sheet_name == 'Quarterly' else df_annual

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
        """
        Get specific metric value

        Parameters:
        -----------
        statement_type : str or StatementType
            Type of financial statement
        metric : str
            Metric name
        year : str or int, optional
            Year (e.g., '2024' or 2024)
        freq : str
            'quarterly' or 'annual'
        """
        if isinstance(statement_type, str):
            statement_type = StatementType(statement_type)

        if not self._quarterly_data:
            self._fetch_data()

        if freq == 'annual' and statement_type in self._annual_data:
            if year:
                year_int = int(year)
                if year_int in self._annual_data[statement_type]:
                    return self._annual_data[statement_type][year_int].get(metric)
                return None
            return {
                year: data.get(metric)
                for year, data in self._annual_data[statement_type].items()
            }

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

    def export_statements_to_excel(self, prefix: str = None) -> None:
        """
        Export all financial statements to separate Excel files

        Parameters:
        -----------
        prefix : str, optional
            Prefix for Excel filenames (default: lowercase symbol)
        """
        if not self._quarterly_data:
            self._fetch_data()

        if prefix is None:
            prefix = self.symbol.lower()

        statements = {
            'Balance_Sheet': f'{prefix}_balance_sheet.xlsx',
            'Cash_Flow': f'{prefix}_cash_flow.xlsx',
            'Income_Statement': f'{prefix}_income_statement.xlsx'
        }

        print("\nExporting financial statements to Excel:")
        print("-" * 40)

        for statement_type, filename in statements.items():
            try:
                # Get quarterly and annual data
                quarterly_data = []
                annual_data = {}

                st = StatementType(statement_type)
                if st in self._quarterly_data:
                    quarterly_data = self._quarterly_data[st]
                if st in self._annual_data:
                    annual_data = self._annual_data[st]

                if quarterly_data:
                    self._save_to_excel(filename, quarterly_data, annual_data)
                    print(f"✓ Created {filename}")
                else:
                    print(f"✗ No data available for {statement_type}")
            except Exception as e:
                print(f"✗ Error creating {filename}: {e}")

        print("\nExport complete!")

    def get_all_metrics(self,
                        statement_type: Union[str, StatementType],
                        year: Optional[Union[str, int]] = None,
                        freq: str = 'annual') -> Union[Dict[str, Any], Dict[str, Dict[str, Any]], None]:
        """
        Get all metrics

        Parameters:
        -----------
        statement_type : str or StatementType
            Type of financial statement
        year : str or int, optional
            Year (e.g., '2024' or 2024)
        freq : str
            'quarterly' or 'annual'
        """
        if isinstance(statement_type, str):
            statement_type = StatementType(statement_type)

        if not self._quarterly_data:
            self._fetch_data()

        if freq == 'annual':
            if statement_type not in self._annual_data:
                return None

            if year:
                year_int = int(year)
                return self._annual_data[statement_type].get(year_int)
            return self._annual_data[statement_type]

        if statement_type not in self._quarterly_data:
            return None

        if year:
            year_str = str(year)
            return {
                quarter['date'].strftime('%Y-%m-%d'): quarter['data']
                for quarter in self._quarterly_data[statement_type]
                if str(quarter['date'].year) == year_str
            }

        return {
            quarter['date'].strftime('%Y-%m-%d'): quarter['data']
            for quarter in self._quarterly_data[statement_type]
        }

    """Example usage"""
