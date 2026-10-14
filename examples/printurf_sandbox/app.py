from totals import add_item


def main():
    prices = [12, 8, 5]
    for price in prices:
        add_item(price)
    print(f"total: {total}")


if __name__ == "__main__":
    main()
