from autogluon.timeseries import TimeSeriesPredictor, TimeSeriesDataFrame
import numpy as np
import pandas as pd
import os
import matplotlib.pyplot as plt



def summarize_results_all_windows(predictor, test_data):
    '''
    Creates a dataframe with mean evaluation metrics calculated for each ticker  during backtesting- MASE, RMSE, WQL
    '''
    print("------------------------------------------------Starting to summarize results------------------------------------")
    num_test_windows = 20
    prediction_length = 5
    tickers = list(test_data.item_ids)
    lb = predictor.leaderboard()
    best_model = lb.iloc[0]["model"] #best model obtained from training

    all_results = []
    for ticker in tickers:
        print("Calculating results for: ", ticker)
        single_ticker_data = test_data.loc[[ticker]]
        ticker_mase_scores = []
        ticker_wql_scores =[]
        ticker_rmse_scores =[]

        for cutoff in range(-num_test_windows* prediction_length, 0, prediction_length):

            scores = predictor.evaluate(single_ticker_data ,model=best_model, cutoff=cutoff, metrics=["RMSE", "MASE", "WQL"])
            ticker_mase_scores.append(scores['MASE'])
            ticker_rmse_scores.append(scores['RMSE'])
            ticker_wql_scores.append(scores['WQL'])
        all_results.append({
            'Ticker': ticker,
            'Mean_MASE': (-1)*np.mean(ticker_mase_scores),
            'Mean_RMSE': (-1)*np.mean(ticker_rmse_scores),
            "Mean WQL": (-1)*np.mean(ticker_wql_scores)
        })

    summary_df = pd.DataFrame(all_results).set_index('Ticker')
    summary_df.to_csv("backtest_results/backtest_summary.csv")
    print(summary_df)



def mean_hit_ratio_all_windows(predictor,  target, test_data, period):
    '''
    Calculates hit ratios for each ticker from backtest results
    '''
    print("------------------------------------------Strting to calculate hit ratios---------------------------------------")
    num_test_windows=20
    predictions_per_window = predictor.backtest_predictions(test_data, num_val_windows=20)
    all_ticker_stats = []
    tickers = list(test_data.item_ids)

    for ticker in tickers:
        print("Hit ratio for : ", ticker)
        ticker_hits = []

        for i, window_forecast in enumerate(predictions_per_window):
            cutoff = -(num_test_windows - i) * period
            # Predictions for this window
            y_pred = window_forecast.loc[ticker]['mean'].values

            start_idx = cutoff
            end_idx = cutoff + period
            if end_idx == 0:
                y_true = test_data.loc[ticker][target].iloc[start_idx:].values
            else:
                y_true = test_data.loc[ticker][target].iloc[start_idx : end_idx].values

            # Hit ratio
            hits = np.sign(y_pred) == np.sign(y_true)
            ticker_hits.append(np.mean(hits))


        all_ticker_stats.append({
            'Ticker': ticker,
            'Hit Ratio': np.mean(ticker_hits)
        })

    df_results = pd.DataFrame(all_ticker_stats).set_index('Ticker')
    df_results.to_csv("backtest_results/hit_ratio_backtest.csv")
    print(df_results.sort_values(by='Hit Ratio', ascending=False))

def calculate_coverage_winkler(predictor, test_data, target_col):
    '''
        Calculates coverage for quantile predictions and WInkler scores for each ticker obtained from backtesting.
    '''

    predictions_list = predictor.backtest_predictions(test_data, num_val_windows=20)
    all_preds = pd.concat(predictions_list)
    common_index = all_preds.index.intersection(test_data.index)

    all_preds = all_preds.loc[common_index]
    y_true = test_data[target_col].loc[common_index]

   

    results_global={}

    # Coverage and coverage error for selected quantiles
    quantiles = [0.05, 0.1, 0.3, 0.9]

    for q in quantiles:
        q_preds = all_preds[str(q)]
        actual_coverage = (y_true < q_preds).mean()
        coverage_error = actual_coverage - q

        results_global[f"Coverage Actual ({q})"] = actual_coverage
        results_global[f"Coverage Error ({q})"] = coverage_error

    # WINKLER SCORE (0.1 - 0.9)
    L = all_preds["0.1"]
    U = all_preds["0.9"]
    s=0.2
    width = U-L
    penalty_low = (2 / s) * (L - y_true) * (y_true < L)
    penalty_high = (2 / s) * (y_true - U) * (y_true > U)
    winkler_per_ticker = (width + penalty_low + penalty_high).groupby(level="item_id").mean()

    ticker_std = test_data.groupby("item_id")['Return_1d'].std()
    winkler_rel = winkler_per_ticker / ticker_std

    df_ticker = pd.DataFrame({
        "Winkler Score (0.1-0.9)": winkler_per_ticker,
        "Winkler Normalized": winkler_rel
    })
    df_ticker.to_csv("backtest_results/winkler_per_ticker.csv")
    df_global = pd.DataFrame([results_global])
    df_global.to_csv("backtest_results/coverage_results.csv", index=False)

    print("Coverage : ")
    print(df_global)
    print("Winkler:")
    print(df_ticker)


def plot_backtest(predictor, test_data, period):
    '''
    Generates the plots with backtest results for each ticker
    '''

    print("------------------------------------Starting to plot backtest------------------------")

    num_test_windows = 20
    tickers = list(test_data.item_ids)
    selected_tickers = tickers[:9]

    os.makedirs("backtest_plots", exist_ok=True)

    predictions_per_window = predictor.backtest_predictions(
        test_data,
        num_val_windows=num_test_windows
    )

    all_predictions = pd.concat(predictions_per_window)

    for ticker in selected_tickers:

        print("Plotting backtest ticker:", ticker)

        plt.figure(figsize=(10, 5))

        predictor.plot(
            test_data,
            all_predictions,
            item_ids=[ticker],
            max_history_length=150,
            quantile_levels=[0.05, 0.1, 0.9, 0.95]
        )

        ax = plt.gca()
        fig = plt.gcf()

        # -----------------------------
        # Transparent dark background
        # -----------------------------
        fig.patch.set_facecolor((0, 0, 0, 0.12))
        ax.set_facecolor((0, 0, 0, 0.03))

        # -----------------------------
        # Remove top/right borders
        # -----------------------------
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        # -----------------------------
        # Grid style
        # -----------------------------
        ax.grid(
            True,
            linestyle="-",
            linewidth=0.6,
            alpha=0.25,
            color="#9aa5b1"
        )

        # -----------------------------
        # Change line colors
        # -----------------------------
        lines = ax.get_lines()

        if len(lines) > 0:
            lines[0].set_color("#2ecc71")   # true data
            lines[0].set_linewidth(2)

        if len(lines) > 1:
            lines[1].set_color("#8e44ad")   # median
            lines[1].set_linewidth(2)

        # -----------------------------
        # Quantile bands
        # -----------------------------
        for collection in ax.collections:
            collection.set_facecolor("#8e44ad")
            collection.set_alpha(0.18)

        # -----------------------------
        # Backtest cutoffs
        # -----------------------------
        for cutoff in range(-num_test_windows * period, 0, period):

            try:
                cutoff_timestamp = test_data.loc[ticker].index[cutoff]

                ax.axvline(
                    cutoff_timestamp,
                    color="red",
                    linestyle="--",
                    alpha=0.35,
                    lw=1
                )

            except IndexError:
                continue

        # -----------------------------
        # Title
        # -----------------------------
        ax.set_title(f"Backtest: {ticker}", fontsize=12)

        # -----------------------------
        # Refresh legend (important!)
        # -----------------------------
        handles, labels = ax.get_legend_handles_labels()
        ax.legend(handles, labels, frameon=False)

        plt.tight_layout()

        # -----------------------------
        # Save transparent PNG
        # -----------------------------
        plt.savefig(
            f"backtest_plots/{ticker}_backtest.png",
            dpi=300,
            transparent=True
        )

        plt.close()



