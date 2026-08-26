from __future__ import annotations

from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from prestashop_client import get_settings, health_check, request_bridge


mcp = MCPServer(
    "prestashop-eletrix",
    instructions=(
        "Read-only operational access to the Eletrix PrestaShop store. "
        "Use these tools for orders, abandoned carts, products, stock, catalogue quality and statistics. "
        "The source bridge accepts only allow-listed SELECT queries. Never claim data was modified. "
        "Amounts labelled estimated are not accounting values."
    ),
)

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)


@mcp.tool(title="Check PrestaShop MCP configuration", annotations=READ_ONLY)
def prestashop_health() -> dict[str, Any]:
    """Validate bridge connectivity, database identity, required tables and read-only security controls."""
    payload = health_check()
    cfg = get_settings()
    return {
        "configured": True,
        "read_only": True,
        "bridge_mode": "fixed_queries_only",
        "database_user": payload.get("server", {}).get("authenticated_db_user"),
        "required_tables": payload.get("tables", {}),
        "shop_id": cfg.shop_id,
        "lang_id": cfg.lang_id,
    }


@mcp.tool(title="PrestaShop operational overview", annotations=READ_ONLY)
def shop_overview(start_date: str = "30daysAgo", end_date: str = "today") -> dict[str, Any]:
    """Core operational KPIs for a date range: orders, value, customers, carts and catalogue/stock counts."""
    return request_bridge("overview", **{"from": start_date, "to": end_date})


@mcp.tool(title="List PrestaShop orders", annotations=READ_ONLY)
def orders_list(
    start_date: str,
    end_date: str,
    page: Annotated[int, Field(ge=1, le=10000)] = 1,
    limit: Annotated[int, Field(ge=1, le=100)] = 50,
    state_id: Annotated[int | None, Field(ge=1)] = None,
    valid_only: bool = False,
) -> dict[str, Any]:
    """List orders with operational state, totals and payment method. Customer email is intentionally omitted from list views."""
    return request_bridge(
        "orders",
        **{"from": start_date, "to": end_date, "page": page, "limit": limit, "state_id": state_id, "valid_only": int(valid_only)},
    )


@mcp.tool(title="Get PrestaShop order details", annotations=READ_ONLY)
def order_details(order_id: Annotated[int, Field(ge=1)]) -> dict[str, Any]:
    """Read one order including lines, totals, state, payment and customer identity needed for operational follow-up."""
    return request_bridge("order_details", order_id=order_id)


@mcp.tool(title="Find abandoned PrestaShop carts", annotations=READ_ONLY)
def abandoned_carts(
    min_age_hours: Annotated[int, Field(ge=1, le=720)] = 2,
    max_age_days: Annotated[int, Field(ge=1, le=365)] = 30,
    page: Annotated[int, Field(ge=1, le=10000)] = 1,
    limit: Annotated[int, Field(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    """Carts with products, no corresponding order, and no update for the requested age. Value is current-catalog estimate excluding tax/shipping."""
    return request_bridge(
        "abandoned_carts",
        min_age_hours=min_age_hours,
        max_age_days=max_age_days,
        page=page,
        limit=limit,
    )


@mcp.tool(title="PrestaShop products summary", annotations=READ_ONLY)
def products_summary() -> dict[str, Any]:
    """Counts of products, active/inactive catalogue entries, combinations/SKUs, manufacturers, images and stock availability."""
    return request_bridge("products_summary")


@mcp.tool(title="Search PrestaShop products", annotations=READ_ONLY)
def products_search(
    query: str = "",
    active: bool | None = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    """Search by product name, reference, EAN or manufacturer and return catalogue/stock quality fields."""
    return request_bridge("products_search", q=query, active=None if active is None else int(active), limit=limit)


@mcp.tool(title="Get PrestaShop product details", annotations=READ_ONLY)
def product_details(product_id: Annotated[int, Field(ge=1)]) -> dict[str, Any]:
    """Read the full catalogue record for one product, including descriptions, SEO metadata, categories, images and stock."""
    return request_bridge("product_details", product_id=product_id)


@mcp.tool(title="PrestaShop stock summary", annotations=READ_ONLY)
def stock_summary(low_stock_default: Annotated[int, Field(ge=0, le=10000)] = 5) -> dict[str, Any]:
    """Operational stock counts including available, zero, negative and low-stock active products."""
    return request_bridge("stock_summary", low_stock_default=low_stock_default)


@mcp.tool(title="Audit PrestaShop catalogue quality", annotations=READ_ONLY)
def product_quality_audit(
    active_only: bool = True,
    limit: Annotated[int, Field(ge=1, le=200)] = 100,
) -> dict[str, Any]:
    """Detect incomplete or suspicious product records: references, EAN format, brand, descriptions, images, SEO, price and stock. Use product_duplicates for repeated identifiers."""
    return request_bridge("product_quality_audit", active_only=int(active_only), limit=limit)


@mcp.tool(title="Find duplicate PrestaShop identifiers", annotations=READ_ONLY)
def product_duplicates(
    limit: Annotated[int, Field(ge=1, le=200)] = 100,
) -> dict[str, Any]:
    """Find repeated product references, EANs, slugs and combination references/EANs without modifying the catalogue."""
    return request_bridge("product_duplicates", limit=limit)


if __name__ == "__main__":
    mcp.run()
