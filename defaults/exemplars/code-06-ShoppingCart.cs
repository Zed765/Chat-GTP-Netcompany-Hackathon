using System;
using System.Collections.Generic;
using System.Linq;

namespace Example.Shop
{
    /// <summary>A shopping cart with quantity rules, discount codes and tax.</summary>
    public sealed class ShoppingCart
    {
        public sealed record Product(string Sku, string Name, decimal UnitPrice, bool Taxable = true);

        public sealed record Line(Product Product, int Quantity)
        {
            public decimal Subtotal => Product.UnitPrice * Quantity;
        }

        private const int MaxQuantityPerLine = 99;
        private readonly Dictionary<string, Line> _lines = new();
        private readonly decimal _taxRate;
        private string? _discountCode;

        public ShoppingCart(decimal taxRate)
        {
            if (taxRate < 0m || taxRate > 1m)
            {
                throw new ArgumentOutOfRangeException(nameof(taxRate), "Tax rate must be between 0 and 1.");
            }

            _taxRate = taxRate;
        }

        public IReadOnlyCollection<Line> Lines => _lines.Values;

        public bool IsEmpty => _lines.Count == 0;

        public void Add(Product product, int quantity = 1)
        {
            if (quantity <= 0)
            {
                throw new ArgumentOutOfRangeException(nameof(quantity), "Quantity must be positive.");
            }

            var current = _lines.TryGetValue(product.Sku, out var line) ? line.Quantity : 0;
            var updated = Math.Min(current + quantity, MaxQuantityPerLine);
            _lines[product.Sku] = new Line(product, updated);
        }

        public bool Remove(string sku) => _lines.Remove(sku);

        public void SetQuantity(string sku, int quantity)
        {
            if (!_lines.TryGetValue(sku, out var line))
            {
                throw new KeyNotFoundException($"No line for {sku}.");
            }

            if (quantity <= 0)
            {
                _lines.Remove(sku);
                return;
            }

            _lines[sku] = line with { Quantity = Math.Min(quantity, MaxQuantityPerLine) };
        }

        public bool ApplyDiscount(string code)
        {
            var known = new[] { "WELCOME10", "FREESHIP", "SUMMER15" };
            if (!known.Contains(code, StringComparer.OrdinalIgnoreCase))
            {
                return false;
            }

            _discountCode = code.ToUpperInvariant();
            return true;
        }

        public decimal Subtotal => _lines.Values.Sum(line => line.Subtotal);

        public decimal Discount => _discountCode switch
        {
            "WELCOME10" => Math.Round(Subtotal * 0.10m, 2),
            "SUMMER15" when Subtotal >= 50m => Math.Round(Subtotal * 0.15m, 2),
            _ => 0m,
        };

        public decimal Shipping => _discountCode == "FREESHIP" || Subtotal >= 80m || IsEmpty ? 0m : 4.90m;

        public decimal Tax
        {
            get
            {
                var taxable = _lines.Values.Where(line => line.Product.Taxable).Sum(line => line.Subtotal);
                var share = Subtotal == 0m ? 0m : taxable / Subtotal;
                return Math.Round((taxable - Discount * share) * _taxRate, 2);
            }
        }

        public decimal Total => Subtotal - Discount + Shipping + Tax;

        public override string ToString() =>
            string.Join(Environment.NewLine, _lines.Values.Select(line =>
                $"{line.Quantity,3} x {line.Product.Name,-24} {line.Subtotal,8:F2}")
                .Append($"Total: {Total:F2}"));
    }
}
