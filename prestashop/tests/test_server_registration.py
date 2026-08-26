from server import mcp


def test_expected_tools_registered():
    assert set(mcp._tool_manager._tools) == {
        "prestashop_health",
        "shop_overview",
        "orders_list",
        "order_details",
        "abandoned_carts",
        "products_summary",
        "products_search",
        "product_details",
        "stock_summary",
        "product_quality_audit",
        "product_duplicates",
    }
