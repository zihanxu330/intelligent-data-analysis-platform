import akshare as ak


def get_stock_list():

    df = ak.stock_info_a_code_name()

    return df


if __name__ == "__main__":

    stocks = get_stock_list()

    print(stocks.head())

    stocks.to_csv(
        "stocks.csv",
        index=False
    )