# src/analysis/analysis_service.py

import numpy as np
import pandas as pd
import math
import random
from datetime import datetime, timedelta
from sklearn.preprocessing import PolynomialFeatures
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score
from app.utils.data.data_service import DataService
import logging
import re

logger = logging.getLogger(__name__)

class AnalysisService:
    @staticmethod
    def calculate_price_appreciation_pct(current_price, highest_price, lowest_price):
        """Calculate price appreciation percentage relative to range"""
        total_range = highest_price - lowest_price
        if total_range > 0:
            current_from_low = current_price - lowest_price
            return (current_from_low / total_range) * 100
        return 0

    @staticmethod
    def find_crossover_points(dates, series1, series2, prices):
        """Find points where two series cross each other"""
        crossover_points = []
        crossover_values = []
        crossover_directions = []
        crossover_prices = []
        
        s1 = np.array(series1)
        s2 = np.array(series2)
        
        diff = s1 - s2
        for i in range(1, len(diff)):
            if diff[i-1] <= 0 and diff[i] > 0:
                cross_value = (s1[i-1] + s2[i-1]) / 2
                crossover_points.append(dates[i])
                crossover_values.append(cross_value)
                crossover_directions.append('down')
                crossover_prices.append(prices[i])
            elif diff[i-1] >= 0 and diff[i] < 0:
                cross_value = (s1[i-1] + s2[i-1]) / 2
                crossover_points.append(dates[i])
                crossover_values.append(cross_value)
                crossover_directions.append('up')
                crossover_prices.append(prices[i])
        
        return crossover_points, crossover_values, crossover_directions, crossover_prices

    @staticmethod
    def format_regression_equation(coefficients, intercept, max_x):
        """Format regression equation string"""
        terms = []
        if coefficients[2] != 0:
            terms.append(f"{coefficients[2]:.2f}(x/{max_x})²")
        if coefficients[1] != 0:
            sign = "+" if coefficients[1] > 0 else ""
            terms.append(f"{sign}{coefficients[1]:.2f}(x/{max_x})")
        if intercept != 0:
            sign = "+" if intercept > 0 else ""
            terms.append(f"{sign}{intercept:.2f}")
        equation = "Ln(y) = " + " ".join(terms)
        return equation

    @staticmethod
    def perform_polynomial_regression(data, future_days=180):
        """Perform polynomial regression analysis with three-component scoring"""
        try:
            # 1. Input validation
            if data is None or data.empty:
                print("Error: Input data is None or empty")
                return {
                    'predictions': [],
                    'upper_band': [],
                    'lower_band': [],
                    'r2': 0,
                    'coefficients': [0, 0, 0],
                    'intercept': 0,
                    'std_dev': 0,
                    'equation': "No data available",
                    'max_x': 0,
                    'total_score': {
                        'score': 0,
                        'rating': 'Error',
                        'components': {
                            'trend': {'score': 0, 'type': 'Unknown'},
                            'return': {'score': 0},
                            'volatility': {'score': 0}
                        }
                    }
                }

            # 2. Get S&P 500 benchmark parameters
            try:
                data_service = DataService()
                # end_date = datetime.now().strftime('%Y-%m-%d')
                end_date = data.index[-1].strftime('%Y-%m-%d')
                start_date = data.index[0].strftime('%Y-%m-%d')
                # start_date = (datetime.now() - timedelta(days=500)).strftime('%Y-%m-%d')
                
                sp500_data = data_service.get_historical_data('^GSPC', start_date, end_date)
                
                if sp500_data is not None and not sp500_data.empty:
                    sp500_data['Log_Close'] = np.log(sp500_data['Close'])
                    X_sp = (sp500_data.index - sp500_data.index[0]).days.values.reshape(-1, 1)
                    y_sp = sp500_data['Log_Close'].values
                    X_sp_scaled = X_sp / (np.max(X_sp) * 1)
                    
                    poly_features = PolynomialFeatures(degree=2)
                    X_sp_poly = poly_features.fit_transform(X_sp_scaled)
                    sp500_model = LinearRegression()
                    sp500_model.fit(X_sp_poly, y_sp)
                    
                    sp500_r2 = r2_score(y_sp, sp500_model.predict(X_sp_poly))
                    sp500_returns = ((sp500_data['Close'].iloc[-1] / sp500_data['Close'].iloc[0]) ** (365 / (sp500_data.index[-1] - sp500_data.index[0]).days) - 1)
                    sp500_annual_return = sp500_returns
                    sp500_daily_returns = sp500_data['Close'].pct_change().dropna()  # still needed for volatility
                    sp500_annual_volatility = sp500_daily_returns.std() * np.sqrt(252)
                                        
                    sp500_params = {
                        'quad_coef': sp500_model.coef_[2],
                        'linear_coef': sp500_model.coef_[1],
                        'r_squared': sp500_r2,
                        'annual_return': sp500_annual_return,
                        'annual_volatility': sp500_annual_volatility
                    }
                else:
                    sp500_params = {
                        'quad_coef': -0.1134,
                        'linear_coef': 0.4700,
                        'r_squared': 0.9505,
                        'annual_return': 0.2384,
                        'annual_volatility': 0.125
                    }
                    logger.info(f"S&P 500 parameters: {sp500_params}")
            except Exception as sp_error:
                print(f"Error calculating S&P 500 parameters: {str(sp_error)}")
                sp500_params = {
                    'quad_coef': -0.1134,
                    'linear_coef': 0.4700,
                    'r_squared': 0.9505,
                    'annual_return': 0.2384,
                    'annual_volatility': 0.125
                }

            # 3. Perform regression analysis
            try:
                data['Log_Close'] = np.log(data['Close'])
                X = (data.index - data.index[0]).days.values.reshape(-1, 1)
                y = data['Log_Close'].values
                X_scaled = X / (np.max(X) * 1)
                
                poly_features = PolynomialFeatures(degree=2)
                X_poly = poly_features.fit_transform(X_scaled)
                model = LinearRegression()
                model.fit(X_poly, y)
                
                coef = model.coef_
                intercept = model.intercept_
                max_x = np.max(X)
                
                # Calculate predictions
                X_future = np.arange(len(data) + future_days).reshape(-1, 1)
                X_future_scaled = X_future / np.max(X) * 1
                X_future_poly = poly_features.transform(X_future_scaled)
                y_pred_log = model.predict(X_future_poly)
                y_pred = np.exp(y_pred_log)
                
                # Calculate confidence bands
                residuals = y - model.predict(X_poly)
                std_dev = np.std(residuals)
                y_pred_upper = np.exp(y_pred_log + 2 * std_dev)
                y_pred_lower = np.exp(y_pred_log - 2 * std_dev)
                
                # Calculate R²
                r2 = r2_score(y, model.predict(X_poly))
                
                # Format equation
                equation = AnalysisService.format_regression_equation(coef, intercept, max_x)
                
            except Exception as e:
                print(f"Error in regression calculation: {str(e)}")
                return {
                    'predictions': data['Close'].values.tolist(),
                    'upper_band': data['Close'].values.tolist(),
                    'lower_band': data['Close'].values.tolist(),
                    'r2': 0,
                    'coefficients': [0, 0, 0],
                    'intercept': 0,
                    'std_dev': 0,
                    'equation': "Regression failed",
                    'max_x': len(data),
                    'total_score': {
                        'score': 0,
                        'rating': 'Error',
                        'components': {
                            'trend': {'score': 0, 'type': 'Unknown', 'details': {}},
                            'return': {'score': 0},
                            'volatility': {'score': 0}
                        }
                    }
                }

            # 4. Calculate scoring
            try:
                
                
                def evaluate_trend_score(quad_coef, linear_coef, r_squared):
                    """
                    Calculate trend score ranging from 0 (most bearish) to 100 (most bullish)
                    based on trend direction, strength, and credibility
                    """
                    try:
                        # 1. Calculate asset's own volatility for benchmarks
                        returns = data['Close'].pct_change().dropna()
                        annual_vol = returns.std() * np.sqrt(252)
                        period_days = len(data)
                        period_years = period_days / 252
                        
                        # Calculate benchmarks using asset's own volatility
                        vol_linear = annual_vol * np.sqrt(period_years)
                        vol_quad = annual_vol / np.sqrt(period_days)
                        
                        # Calculate normalized impacts
                        linear_impact = linear_coef / vol_linear
                        quad_impact = quad_coef / vol_quad
                        
                        # 2. Calculate base trend score (50 is neutral)
                        trend_score = 50
                        
                        # Determine trend type
                        trend_type = {
                            'accelerating_up': quad_coef > 0 and linear_coef > 0,
                            'accelerating_down': quad_coef < 0 and linear_coef < 0,
                            'reversal_up': quad_coef > 0 and linear_coef < 0,
                            'reversal_down': quad_coef < 0 and linear_coef > 0
                        }
                        
                        # Calculate strengths with modified scaling
                        future_strength = min(1.0, abs(quad_impact)/30)  # Less aggressive scaling
                        historic_strength = min(1.0, abs(linear_impact))
                        
                        # Apply weighted impacts based on trend type
                        if trend_type['accelerating_up']:
                            trend_score += (future_strength * 35 + historic_strength * 25)
                        elif trend_type['accelerating_down']:
                            trend_score -= (future_strength * 35 + historic_strength * 25)
                        elif trend_type['reversal_up']:
                            trend_score += (future_strength * 35 - historic_strength * 15)
                        elif trend_type['reversal_down']:
                            # Give more weight to linear when it's strong
                            if historic_strength > 0.7:  # Strong linear uptrend
                                trend_score += historic_strength * 35
                            elif future_strength > historic_strength:
                                trend_score -= future_strength * 25
                            else:
                                trend_score += historic_strength * 20
                        
                        # Apply confidence adjustment with higher base
                        r_squared_multiplier = 0.6 + (0.4 * math.pow(r_squared, 2))  # Range: 0.7-1.0
                        
                        # Calculate final score
                        final_score = trend_score * r_squared_multiplier
                        final_score = min(100, max(0, final_score))
                        
                        # Calculate ratio for compatibility
                        ratio = abs(quad_coef / linear_coef) if linear_coef != 0 else float('inf')
                        
                        # Determine credibility level
                        if r_squared >= 0.90:
                            credibility_level = 5  # Very High
                        elif r_squared >= 0.80:
                            credibility_level = 4  # High
                        elif r_squared >= 0.70:
                            credibility_level = 3  # Moderate
                        elif r_squared >= 0.60:
                            credibility_level = 2  # Low
                        else:
                            credibility_level = 1  # Very Low
                            
                        return final_score, ratio, credibility_level
                        
                    except Exception as e:
                        print(f"Error in trend score calculation: {str(e)}")
                        return 50, 0, 1  # Return neutral score on error
                                
                
                def score_metric(value, benchmark, metric_type='return'):
                    """
                    Score metrics based on type:
                    - Returns: Use difference in percentage points (5% steps)
                    - Volatility: Use ratio comparison
                    
                    Parameters:
                    value: actual value
                    benchmark: benchmark value
                    metric_type: 'return' or 'volatility'
                    """
                    if metric_type == 'return':
                        # For returns, use absolute difference in percentage points
                        base_score = 60
                        diff = (value - benchmark) * 100 
                        if diff >= 0:
                            # For positive diff, add 1 point per 2%
                            points_change = diff / 2
                        else:
                            # For negative diff, subtract 2 points per 1%
                            points_change = diff * 2
                        
                        # Calculate final score
                        final_score = base_score + points_change
                        
                        # Cap at maximum of 100 and minimum of 25
                        if final_score > 100:
                            return 100
                        if final_score < 25:
                            return 25
                            
                        return round(final_score)
                    # Convert to percentage points
                        
                        # Score based on 5% steps from -30% to +30%
                        
                        
                        
                    else:  # volatility
                        # For volatility, use ratio (lower is better)
                        ratio = value / benchmark
                        
                        if ratio <= 0.6: return 100    # 40% or less volatility
                        if ratio <= 0.7: return 90
                        if ratio <= 0.8: return 85
                        if ratio <= 0.9: return 80
                        if ratio <= 1.0: return 75     # Equal to benchmark
                        if ratio <= 1.2: return 70
                        if ratio <= 1.4: return 65
                        if ratio <= 1.6: return 60
                        if ratio <= 1.8: return 55
                        if ratio <= 2.0: return 50
                        return 40                       # >50% more volatile

               
                # Calculate returns and volatility
                returns = data['Close'].pct_change().dropna()
                annual_return = ((data['Close'].iloc[-1] / data['Close'].iloc[0]) ** (365 / (data.index[-1] - data.index[0]).days) - 1)
                annual_volatility = returns.std() * np.sqrt(252)
                logger.info(f"sp500_params: {sp500_params}")
                logger.info(f"annual_return: {annual_return}")
                logger.info(f"annual_volatility: {annual_volatility}")
                
                # Calculate trend score
                trend_score, ratio, credibility_level = evaluate_trend_score(coef[2], coef[1], r2)
                
                # Calculate other scores
                 # Usage in scoring section:
                return_score = score_metric(annual_return, sp500_params['annual_return'], 'return')
                vol_score = score_metric(annual_volatility, sp500_params['annual_volatility'], 'volatility')
                
                # Calculate raw score
                weights = {'trend': 0.3, 'return': 0.6, 'volatility': 0.10}
                raw_score = (
                    trend_score * weights['trend'] +
                    return_score * weights['return'] +
                    vol_score * weights['volatility']
                )

                # Calculate SP500's raw score
                sp500_trend_score, _, _ = evaluate_trend_score(
                    sp500_params['quad_coef'], 
                    sp500_params['linear_coef'],
                    sp500_params['r_squared']
                )
                sp500_return_score = score_metric(sp500_params['annual_return'], sp500_params['annual_return'], 'return')
                sp500_vol_score = score_metric(sp500_params['annual_volatility'], sp500_params['annual_volatility'], 'volatility')

                sp500_raw_score = (
                    sp500_trend_score * weights['trend'] +
                    sp500_return_score * weights['return'] +
                    sp500_vol_score * weights['volatility']
                )
                logger.info(f"SP500 raw score: {sp500_raw_score}")
                logger.info(f"SP500 trend score: {sp500_trend_score}")
                logger.info(f"SP500 return score: {sp500_return_score}")
                logger.info(f"SP500 volatility score: {sp500_vol_score}")
                logger.info(f"asset raw score: {raw_score}")
                logger.info(f"asset trend score: {trend_score}")
                logger.info(f"asset return score: {return_score}")
                logger.info(f"asset volatility score: {vol_score}")
                
                scaling_factor =  75/ sp500_raw_score

                # Calculate final scaled score
                final_score = min(95, raw_score * scaling_factor)
                final_score =  round(random.uniform(final_score-2, final_score+2), 2)
                # Determine rating
                if final_score >= 90: rating = 'Excellent'
                elif final_score >= 75: rating = 'Very Good'
                elif final_score >= 65: rating = 'Good'
                elif final_score >= 40: rating = 'Fair'
                else: rating = 'Poor'

            except Exception as e:
                print(f"Error in scoring calculation: {str(e)}")
                return_score = vol_score = trend_score = final_score = 0
                rating = 'Error'
                ratio = 0
                credibility_level = 0

            # 5. Return complete results
            return {
                'predictions': y_pred.tolist(),
                'upper_band': y_pred_upper.tolist(),
                'lower_band': y_pred_lower.tolist(),
                'r2': float(r2),
                'coefficients': coef.tolist(),
                'intercept': float(intercept),
                'std_dev': float(std_dev),
                'equation': equation,
                'max_x': int(max_x),
                'total_score': {
                    'score': float(final_score),
                    'raw_score': float(raw_score),
                    'rating': rating,
                    'components': {
                        'trend': {
                            'score': float(trend_score),
                            'details': {
                                'ratio': float(ratio),
                                'credibility_level': credibility_level,
                                'quad_coef': float(coef[2]),
                                'linear_coef': float(coef[1])
                            }
                        },
                        'return': {
                            'score': float(return_score),
                            'value': float(annual_return)
                        },
                        'volatility': {
                            'score': float(vol_score),
                            'value': float(annual_volatility)
                        }
                    },
                    'scaling': {
                        'factor': float(scaling_factor),
                        'sp500_base': float(sp500_raw_score)
                    },
                    'weights': weights
                }
            }

        except Exception as e:
            print(f"Error in polynomial regression: {str(e)}")
            return {
                'predictions': data['Close'].values.tolist() if data is not None else [],
                'upper_band': data['Close'].values.tolist() if data is not None else [],
                'lower_band': data['Close'].values.tolist() if data is not None else [],
                'r2': 0,
                'coefficients': [0, 0, 0],
                'intercept': 0,
                'std_dev': 0,
                'equation': "Error occurred",
                'max_x': len(data) if data is not None else 0,
                'total_score': {
                    'score': 0,
                    'raw_score': 0,
                    'rating': 'Error',
                    'components': {
                        'trend': {'score': 0, 'details': {}},
                        'return': {'score': 0, 'value': 0},
                        'volatility': {'score': 0, 'value': 0}
                    }
                }
            }
    
    
    @staticmethod
    def calculate_growth_rates(df):
        """Calculate period-over-period growth rates for financial metrics"""
        growth_rates = {}
        
        for metric in df.index:
            values = df.loc[metric][:-1]  # Exclude CAGR column
            if len(values) > 1:
                growth_rates[metric] = []
                for i in range(1, len(values)):
                    prev_val = float(values.iloc[i-1])
                    curr_val = float(values.iloc[i])
                    if prev_val and prev_val != 0:  # Avoid division by zero
                        growth = ((curr_val / prev_val) - 1) * 100
                        growth_rates[metric].append(growth)
                    else:
                        growth_rates[metric].append(None)
        
        return growth_rates

    
    
    @staticmethod
    def calculate_rolling_r2(data, lookback_days=365):
        """Calculate rolling R-square values for regression analysis"""
        analysis_dates = []
        r2_values = []
        
        for current_date in data.index:
            year_start = current_date - timedelta(days=lookback_days)
            mask = (data.index <= current_date)
            period_data = data.loc[mask].copy()  # Create explicit copy
            
            if (current_date - period_data.index[0]).days > lookback_days:
                period_data = period_data[period_data.index > year_start]
            
            if len(period_data) < 20:
                continue
                
            try:
                # Calculate log returns
                period_data.loc[:, 'Log_Close'] = np.log(period_data['Close'])
                
                X = (period_data.index - period_data.index[0]).days.values.reshape(-1, 1)
                y = period_data['Log_Close'].values
                X_scaled = X / (np.max(X) * 1)
                
                poly_features = PolynomialFeatures(degree=2)
                X_poly = poly_features.fit_transform(X_scaled)
                model = LinearRegression()
                model.fit(X_poly, y)
                
                r2 = r2_score(y, model.predict(X_poly))
                
                analysis_dates.append(current_date)
                r2_values.append(r2 * 100)
                
            except Exception as e:
                print(f"Error calculating R² for {current_date}: {str(e)}")
                continue
        
        return analysis_dates, r2_values

    
    @staticmethod
    def analyze_stock_data(data, crossover_days=365, lookback_days=365):
        """Perform comprehensive stock analysis"""
        logger = logging.getLogger(__name__)
        logger.debug(f"Starting stock analysis with shape: {data.shape}")
        
        try:
            result_data = []
            
            for current_date in data.index:
                # Get data for R-square calculation (lookback_days)
                r2_start = current_date - timedelta(days=lookback_days)
                r2_data = data.loc[data.index <= current_date].copy()
                if (current_date - r2_data.index[0]).days > lookback_days:
                    r2_data = r2_data[r2_data.index > r2_start]
                
                # Get data for technical indicators (crossover_days)
                tech_start = current_date - timedelta(days=crossover_days)
                period_data = data.loc[data.index <= current_date].copy()
                if (current_date - period_data.index[0]).days > crossover_days:
                    period_data = period_data[period_data.index > tech_start]
                
                if len(period_data) < 20:  # Minimum data points needed
                    continue
                
                # Calculate technical metrics using crossover window
                current_price = period_data['Close'].iloc[-1]
                highest_price = period_data['Close'].max()
                lowest_price = period_data['Close'].min()
                
                # Calculate retracement ratio
                total_move = highest_price - lowest_price
                if total_move > 0:
                    current_retracement = highest_price - current_price
                    ratio = (current_retracement / total_move) * 100
                else:
                    ratio = 0
                
                # Calculate price appreciation
                appreciation_pct = AnalysisService.calculate_price_appreciation_pct(
                    current_price, highest_price, lowest_price)
                
                # Calculate R-square using lookback window
                try:
                    if len(r2_data) >= 20:  # Ensure enough data for R² calculation
                        r2_data.loc[:, 'Log_Close'] = np.log(r2_data['Close'])
                        X = (r2_data.index - r2_data.index[0]).days.values.reshape(-1, 1)
                        y = r2_data['Log_Close'].values
                        X_scaled = X / np.max(X)
                        
                        poly_features = PolynomialFeatures(degree=2)
                        X_poly = poly_features.fit_transform(X_scaled)
                        model = LinearRegression()
                        model.fit(X_poly, y)
                        
                        r2 = r2_score(y, model.predict(X_poly))
                        r2_pct = r2 * 100
                        
                        # logger.debug(f"R² for {current_date}: {r2_pct:.2f}% (using {len(r2_data)} days)")
                    else:
                        r2_pct = None
                        # logger.debug(f"Insufficient data for R² calculation at {current_date}")
                        
                except Exception as e:
                    logger.error(f"Error calculating R² for {current_date}: {str(e)}")
                    r2_pct = None
                
                # Store results
                result_data.append({
                    'Date': current_date,
                    'Close': current_price,
                    'High': highest_price,
                    'Low': lowest_price,
                    'Retracement_Ratio_Pct': ratio,
                    'Price_Position_Pct': appreciation_pct,
                    'R2_Pct': r2_pct
                })
            
            # Create DataFrame
            df = pd.DataFrame(result_data)
            df.set_index('Date', inplace=True)
            
            # Copy original OHLCV columns
            for col in ['Open', 'Volume', 'Dividends', 'Stock Splits']:
                if col in data.columns:
                    df[col] = data[col]
                    
            logger.info("Analysis complete")
            # if 'R2_Pct' in df.columns:
            #     valid_r2 = df['R2_Pct'].dropna()
                # if not valid_r2.empty:
                #     logger.info(f"R² Stats - Mean: {valid_r2.mean():.2f}%, Min: {valid_r2.min():.2f}%, Max: {valid_r2.max():.2f}%")
            
            return df
            
        except Exception as e:
            logger.error(f"Error in analyze_stock_data: {str(e)}", exc_info=True)
            raise
        
        
    @staticmethod
    def analyze_stock_data_old(data, crossover_days=365):
        """Perform comprehensive stock analysis"""
        analysis_dates = []
        ratios = []
        prices = []
        highest_prices = []
        lowest_prices = []
        appreciation_pcts = []
        
        for current_date in data.index:
            year_start = current_date - timedelta(days=crossover_days)
            mask = (data.index <= current_date)  # Include all data up to current date
            period_data = data.loc[mask]
            
            # If we have more than crossover_days of data, limit to the lookback period
            if (current_date - period_data.index[0]).days > crossover_days:
                period_data = period_data[period_data.index > year_start]
            
            # Only calculate if we have at least some minimum data points
            if len(period_data) < 2:  # Reduced minimum requirement to 2 points
                continue
                
            current_price = period_data['Close'].iloc[-1]
            highest_price = period_data['Close'].max()
            lowest_price = period_data['Close'].min()
            
            # Calculate ratio
            total_move = highest_price - lowest_price
            if total_move > 0:
                current_retracement = highest_price - current_price
                ratio = (current_retracement / total_move) * 100
            else:
                ratio = 0
                
            # Calculate appreciation percentage
            appreciation_pct = AnalysisService.calculate_price_appreciation_pct(
                current_price, highest_price, lowest_price)
            
            analysis_dates.append(current_date)
            ratios.append(ratio)
            prices.append(current_price)
            highest_prices.append(highest_price)
            lowest_prices.append(lowest_price)
            appreciation_pcts.append(appreciation_pct)
            
        return pd.DataFrame({
            'Date': analysis_dates,
            'Price': prices,
            'High': highest_prices,
            'Low': lowest_prices,
            'Retracement_Ratio_Pct': ratios,
            'Price_Position_Pct': appreciation_pcts
        })



# app/utils/analysis/analysis_service.py

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import logging
from ..config.analyze_config import AnalyzeConfig
from apify_client import ApifyClient
from textblob import TextBlob
from nltk.sentiment.vader import SentimentIntensityAnalyzer
import nltk
import os

class NewsAnalysisService:
    def __init__(self):
        """Initialize news analysis service"""
        self.logger = logging.getLogger(__name__)
        self.client = ApifyClient(os.getenv('APIFY_TOKEN'))
        
        try:
            nltk.download('vader_lexicon')
            self.vader = SentimentIntensityAnalyzer()
        except Exception as e:
            self.logger.error(f"Error initializing VADER: {e}")
            self.vader = None

    def get_news(self, symbols: List[str], limit: int = 10) -> List[Dict]:
        """Fetch news from TradingView via Apify"""
        run_input = {
            "symbols": symbols,
            "proxy": {"useApifyProxy": True, "apifyProxyCountry": "US"},
            "resultsLimit": limit,
        }
        
        try:
            run = self.client.actor("mscraper/tradingview-news-scraper").call(run_input=run_input)
            dataset_id = run["defaultDatasetId"]
            self.logger.info(f"Dataset ID: {dataset_id}")
            return list(self.client.dataset(dataset_id).iterate_items())
        except Exception as e:
            self.logger.error(f"Error fetching news: {str(e)}")
            return []
    def truncate_text(self, text: str, max_length: int = 5000) -> str:  # Increased max_length to 5000
        """
        Truncate text to specified length (if needed)
        Default is now 5000 characters to ensure we get full content
        """
        if not text:
            return ""
            
        # Just return the full text without truncation
        return text

    def analyze_sentiment(self, text: str) -> Dict:
        """
        Analyze sentiment using TextBlob and VADER
        """
        try:
            # TextBlob analysis
            blob = TextBlob(text)
            textblob_polarity = blob.sentiment.polarity
            textblob_subjectivity = blob.sentiment.subjectivity
            
            # VADER analysis
            vader_scores = self.vader.polarity_scores(text)
            compound_score = vader_scores['compound']
            
            # Determine overall sentiment
            if compound_score >= 0.05:
                sentiment = "POSITIVE"
                if compound_score > 0.5:
                    explanation = "Strong positive sentiment"
                else:
                    explanation = "Moderately positive sentiment"
            elif compound_score <= -0.05:
                sentiment = "NEGATIVE"
                if compound_score < -0.5:
                    explanation = "Strong negative sentiment"
                else:
                    explanation = "Moderately negative sentiment"
            else:
                sentiment = "NEUTRAL"
                explanation = "Neutral or mixed sentiment"
            
            # Calculate confidence
            confidence = (abs(compound_score) + abs(textblob_polarity)) / 2
            
            return {
                "overall_sentiment": sentiment,
                "explanation": explanation,
                "confidence": confidence,
                "scores": {
                    "textblob_polarity": textblob_polarity,
                    "textblob_subjectivity": textblob_subjectivity,
                    "vader_compound": compound_score,
                    "vader_pos": vader_scores['pos'],
                    "vader_neg": vader_scores['neg'],
                    "vader_neu": vader_scores['neu']
                }
            }
        except Exception as e:
            self.logger.error(f"Error in sentiment analysis: {str(e)}")
            return {
                "overall_sentiment": "NEUTRAL",
                "explanation": "Error in analysis",
                "confidence": 0,
                "scores": {}
            }

    def extract_metrics_with_context(self, text: str) -> Dict:
        """
        Extract key financial metrics with surrounding context
        """
        metrics = {
            "percentages": [],
            "percentage_contexts": [],
            "currencies": [],
            "currency_contexts": [],
            "dates": []
        }
        
        try:
            # Find percentages with context - improved pattern
            # This pattern now handles multiple percentages in a sentence and complex sentence structures
            percentage_matches = re.finditer(r'([^.!?\n]*?\b(\d+\.?\d*)%[^.!?\n]*)', text)
            
            for match in percentage_matches:
                full_context = match.group(1).strip()
                percentage = float(match.group(2))
                
                # Clean up the context
                context = full_context
                if context.startswith('and '):
                    context = context[4:]
                if context.startswith(', '):
                    context = context[2:]
                    
                metrics["percentages"].append(percentage)
                metrics["percentage_contexts"].append(context)
            
            # Find currency amounts with context - improved pattern
            currency_matches = re.finditer(r'([^.!?\n]*?\$(\d+(?:\.\d{1,2})?(?:\s*(?:million|billion|trillion))?)[^.!?\n]*)', text)
            for match in currency_matches:
                context = match.group(1).strip()
                amount = match.group(2)
                
                # Clean up the context
                if context.startswith('and '):
                    context = context[4:]
                if context.startswith(', '):
                    context = context[2:]
                    
                metrics["currencies"].append(amount)
                metrics["currency_contexts"].append(context)
            
            # Find dates
            dates = re.findall(r'\d{1,2}[-/]\d{1,2}[-/]\d{2,4}', text)
            metrics["dates"] = dates
            
        except Exception as e:
            self.logger.error(f"Error extracting metrics: {str(e)}")
            self.logger.error(f"Text being processed: {text[:200]}...")  # Log the beginning of the text
            
        return metrics
        
    def generate_summary(self, text: str, max_sentences: int = 3) -> Dict:
        """
        Generate multiple types of summaries of the text
        
        Args:
            text (str): Text to summarize
            max_sentences (int): Maximum number of sentences in summary
            
        Returns:
            Dict: Different types of summaries
        """
        try:
            if not text:
                return {
                    "key_points": "",
                    "market_impact": "",
                    "brief": ""
                }
                
            # Create TextBlob object
            blob = TextBlob(text)
            sentences = blob.sentences
            
            if not sentences:
                return {
                    "key_points": text,
                    "market_impact": text,
                    "brief": text
                }
                
            # Get word frequencies
            word_frequencies = {}
            important_words = set(['increased', 'decreased', 'growth', 'decline', 'up', 'down',
                                'rising', 'falling', 'higher', 'lower', 'profit', 'loss',
                                'revenue', 'earnings', 'guidance', 'forecast', 'outlook',
                                'announced', 'reported', 'launched', 'acquired', 'merger'])
                                
            for word in blob.words:
                word = word.lower()
                if word.isalnum():
                    word_frequencies[word] = word_frequencies.get(word, 0) + 1
                    
            # Score sentences
            sentence_scores = []
            market_related_sentences = []
            for sentence in sentences:
                # General importance score
                score = sum(word_frequencies.get(word.lower(), 0) 
                          for word in sentence.words if word.lower().isalnum())
                          
                # Market impact score
                market_words = sum(1 for word in sentence.words 
                                 if word.lower() in important_words)
                
                sentence_str = str(sentence)
                sentence_scores.append((score, sentence_str))
                
                if market_words > 0:
                    market_related_sentences.append((market_words, sentence_str))
            
            # Generate different types of summaries
            
            # 1. Key Points (based on word frequency)
            top_sentences = sorted(sentence_scores, reverse=True)[:max_sentences]
            key_points = ' '.join(sent[1] for sent in sorted(top_sentences,
                                key=lambda x: text.find(x[1])))
            
            # 2. Market Impact (focusing on market-related sentences)
            market_sentences = sorted(market_related_sentences, reverse=True)[:2]
            market_impact = ' '.join(sent[1] for sent in sorted(market_sentences,
                                   key=lambda x: text.find(x[1])))
            
            # 3. Brief Summary (first and last sentences)
            brief = str(sentences[0])
            if len(sentences) > 1:
                brief += ' ' + str(sentences[-1])
            
            return {
                "key_points": key_points,
                "market_impact": market_impact,
                "brief": brief
            }
            
        except Exception as e:
            self.logger.error(f"Error generating summary: {str(e)}")
            return {
                "key_points": "Unable to generate summary.",
                "market_impact": "Unable to analyze market impact.",
                "brief": "Unable to generate brief summary."
            }
        metrics = {
            "percentages": [],
            "percentage_contexts": [],
            "currencies": [],
            "currency_contexts": [],
            "dates": []
        }
        
        try:
            # Find percentages with context - improved pattern
            # This pattern now handles multiple percentages in a sentence and complex sentence structures
            percentage_matches = re.finditer(r'([^.!?\n]*?\b(\d+\.?\d*)%[^.!?\n]*)', text)
            
            for match in percentage_matches:
                full_context = match.group(1).strip()
                percentage = float(match.group(2))
                
                # Clean up the context
                context = full_context
                if context.startswith('and '):
                    context = context[4:]
                if context.startswith(', '):
                    context = context[2:]
                    
                metrics["percentages"].append(percentage)
                metrics["percentage_contexts"].append(context)
            
            # Find currency amounts with context - improved pattern
            currency_matches = re.finditer(r'([^.!?\n]*?\$(\d+(?:\.\d{1,2})?(?:\s*(?:million|billion|trillion))?)[^.!?\n]*)', text)
            for match in currency_matches:
                context = match.group(1).strip()
                amount = match.group(2)
                
                # Clean up the context
                if context.startswith('and '):
                    context = context[4:]
                if context.startswith(', '):
                    context = context[2:]
                    
                metrics["currencies"].append(amount)
                metrics["currency_contexts"].append(context)
            
            # Find dates
            dates = re.findall(r'\d{1,2}[-/]\d{1,2}[-/]\d{2,4}', text)
            metrics["dates"] = dates
            
        except Exception as e:
            self.logger.error(f"Error extracting metrics: {str(e)}")
            self.logger.error(f"Text being processed: {text[:200]}...")  # Log the beginning of the text
            
        return metrics

    def format_articles(self, articles: List[Dict]) -> List[Dict]:
        """Format and analyze articles"""
        formatted = []
        
        for article in articles:
            try:
                # Get the full content
                content = article.get("descriptionText", "")
                if not content:
                    # Try alternate field names that might contain the content
                    content = (article.get("description", "") or 
                             article.get("text", "") or 
                             article.get("content", ""))
                
                self.logger.info(f"Content length: {len(content)} characters")
                
                published_date = datetime.fromtimestamp(
                    article.get("published", 0) / 1000
                ).strftime("%Y-%m-%d %H:%M:%S")

                # Run analyses
                sentiment = self.analyze_sentiment(content)
                metrics = self.extract_metrics_with_context(content)
                
                formatted_article = {
                    "title": article.get("title", ""),
                    "content": content,  # Full content
                    "summary": self.generate_summary(content),  # Add summary
                    "url": article.get("storyPath", ""),
                    "published_at": published_date,
                    "source": article.get("source", "Unknown"),
                    "symbols": [symbol["symbol"] for symbol in article.get("relatedSymbols", [])],
                    "sentiment": sentiment,
                    "metrics": metrics
                }
                
                formatted.append(formatted_article)
                
            except Exception as e:
                self.logger.error(f"Error formatting article: {str(e)}")
                continue
                
        return formatted

    
    def analyze_sentiment(self, text: str) -> Dict:
        """Analyze text sentiment"""
        try:
            # TextBlob analysis
            blob = TextBlob(text)
            textblob_score = blob.sentiment.polarity
            
            # VADER analysis
            vader_scores = self.vader.polarity_scores(text)
            compound_score = vader_scores['compound']
            
            # Determine sentiment
            if compound_score >= 0.05:
                sentiment = "POSITIVE"
            elif compound_score <= -0.05:
                sentiment = "NEGATIVE"
            else:
                sentiment = "NEUTRAL"
                
            return {
                "sentiment": sentiment,
                "score": compound_score,
                "confidence": abs(compound_score)
            }
        except Exception as e:
            self.logger.error(f"Error analyzing sentiment: {e}")
            return {"sentiment": "NEUTRAL", "score": 0, "confidence": 0}

    def analyze_articles(self, articles: List[Dict]) -> List[Dict]:
        """Analyze a list of news articles"""
        analyzed = []
        for article in articles:
            try:
                content = article.get("descriptionText", "")
                sentiment = self.analyze_sentiment(content)
                
                analyzed.append({
                    "title": article.get("title", ""),
                    "content": content,
                    "url": article.get("storyPath", ""),
                    "published_at": datetime.fromtimestamp(
                        article.get("published", 0) / 1000
                    ).strftime("%Y-%m-%d %H:%M:%S"),
                    "source": article.get("source", ""),
                    "sentiment": sentiment
                })
            except Exception as e:
                self.logger.error(f"Error analyzing article: {e}")
                continue
                
        return analyzed

    def get_news_analysis(self, symbol: str, days: int = 7) -> Dict:
        """Get complete news analysis for a symbol"""
        articles = self.get_news(symbol, days)
        analyzed_articles = self.analyze_articles(articles)
        
        # Calculate summary statistics
        if analyzed_articles:
            positive = sum(1 for a in analyzed_articles 
                         if a['sentiment']['sentiment'] == 'POSITIVE')
            negative = sum(1 for a in analyzed_articles 
                         if a['sentiment']['sentiment'] == 'NEGATIVE')
            neutral = sum(1 for a in analyzed_articles 
                         if a['sentiment']['sentiment'] == 'NEUTRAL')
            avg_score = sum(a['sentiment']['score'] for a in analyzed_articles) / len(analyzed_articles)
            
            summary = {
                "total_articles": len(analyzed_articles),
                "sentiment_distribution": {
                    "positive": positive,
                    "negative": negative,
                    "neutral": neutral
                },
                "average_sentiment": avg_score
            }
        else:
            summary = {
                "total_articles": 0,
                "sentiment_distribution": {"positive": 0, "negative": 0, "neutral": 0},
                "average_sentiment": 0
            }
            
        return {
            "summary": summary,
            "articles": analyzed_articles
        }