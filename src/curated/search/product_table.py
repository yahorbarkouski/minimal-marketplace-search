"""Every product's price as an array, so a query's price limits become one boolean mask over products."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
from numpy.typing import NDArray

from curated.domain import Filters, Product, ProductId


class ProductTable:
    """One row per product in ascending product_id order; arms and masks refer to products by these rows."""

    def __init__(self, products: Mapping[ProductId, Product]) -> None:
        self.ids = tuple(sorted(products))
        self._row_of = {product_id: row for row, product_id in enumerate(self.ids)}
        prices = (products[product_id].price for product_id in self.ids)
        self._prices = np.fromiter((np.nan if price is None else price for price in prices), dtype=np.float64)

    def __len__(self) -> int:
        return len(self.ids)

    def rows(self, product_ids: Sequence[ProductId]) -> NDArray[np.intp]:
        """The table row of each product, in the given order."""
        missing = [product_id for product_id in product_ids if product_id not in self._row_of]
        if missing:
            raise ValueError(f"{len(missing)} products are not in the product table, such as {missing[:3]}")
        return np.fromiter(
            (self._row_of[product_id] for product_id in product_ids), dtype=np.intp, count=len(product_ids)
        )

    def mask(self, filters: Filters) -> NDArray[np.bool_]:
        """True for each row within the limits. Bounds are inclusive. An unknown price is NaN, and NaN fails every
        comparison, so a product whose price is unknown is never excluded."""
        admitted = np.ones(len(self.ids), dtype=np.bool_)
        if filters.price_min is not None:
            admitted &= ~(self._prices < filters.price_min)
        if filters.price_max is not None:
            admitted &= ~(self._prices > filters.price_max)
        return admitted
