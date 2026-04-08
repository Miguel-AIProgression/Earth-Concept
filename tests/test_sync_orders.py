from sync_orders import transform_order, transform_order_line, parse_odata_date


def test_parse_odata_date():
    assert parse_odata_date("/Date(1775692800000)/") == "2026-04-09"
    assert parse_odata_date(None) is None
    assert parse_odata_date("") is None


def test_transform_order():
    raw = {
        "OrderID": "abc-123",
        "OrderNumber": 9527,
        "OrderDate": "/Date(1775692800000)/",
        "DeliveryStatus": 12,
        "DeliveryStatusDescription": "Open",
        "InvoiceStatus": 0,
        "InvoiceStatusDescription": "",
        "CreatorFullName": "Kantoor EARTH",
        "OrderedByName": "Grand Hotel Krasnapolsky",
        "Description": "PO 4600130365",
        "YourRef": "4600130365",
        "DeliveryDate": "/Date(1775952000000)/",
        "AmountDC": 1234.56,
    }
    result = transform_order(raw)

    assert result["exact_order_id"] == "abc-123"
    assert result["order_number"] == 9527
    assert result["creator"] == "Kantoor EARTH"
    assert result["amount"] == 1234.56
    assert result["order_date"] is not None


def test_transform_order_line():
    raw = {
        "ID": "line-1",
        "ItemCode": "EW72306",
        "ItemDescription": "Earth Water Still 75cl",
        "Quantity": 84.0,
        "QuantityDelivered": 0.0,
        "NetPrice": 12.25,
        "Amount": 1029.0,
        "DeliveryDate": "/Date(1775952000000)/",
    }
    result = transform_order_line(raw, order_id="order-uuid-123")

    assert result["exact_line_id"] == "line-1"
    assert result["item_code"] == "EW72306"
    assert result["quantity"] == 84.0
    assert result["order_id"] == "order-uuid-123"
