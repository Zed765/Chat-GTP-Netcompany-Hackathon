// Formatting and arithmetic for prices held as integer minor units (cents).

export type Currency = "EUR" | "USD" | "GBP" | "JPY";

export interface Money {
  readonly amount: number;
  readonly currency: Currency;
}

const MINOR_UNITS: Record<Currency, number> = { EUR: 2, USD: 2, GBP: 2, JPY: 0 };

export class CurrencyMismatch extends Error {
  constructor(left: Currency, right: Currency) {
    super(`Cannot combine ${left} with ${right}`);
    this.name = "CurrencyMismatch";
  }
}

export function money(value: number, currency: Currency): Money {
  const factor = 10 ** MINOR_UNITS[currency];
  return { amount: Math.round(value * factor), currency };
}

function sameCurrency(left: Money, right: Money): void {
  if (left.currency !== right.currency) throw new CurrencyMismatch(left.currency, right.currency);
}

export function add(left: Money, right: Money): Money {
  sameCurrency(left, right);
  return { amount: left.amount + right.amount, currency: left.currency };
}

export function subtract(left: Money, right: Money): Money {
  sameCurrency(left, right);
  return { amount: left.amount - right.amount, currency: left.currency };
}

export function multiply(value: Money, factor: number): Money {
  return { amount: Math.round(value.amount * factor), currency: value.currency };
}

/** Splits an amount into parts that add up exactly, giving the remainder to the first parts. */
export function allocate(value: Money, ratios: number[]): Money[] {
  const total = ratios.reduce((sum, ratio) => sum + ratio, 0);
  if (total <= 0) throw new RangeError("ratios must add up to more than zero");
  const shares = ratios.map((ratio) => Math.floor((value.amount * ratio) / total));
  let remainder = value.amount - shares.reduce((sum, share) => sum + share, 0);
  return shares.map((share) => {
    const extra = remainder > 0 ? 1 : 0;
    remainder -= extra;
    return { amount: share + extra, currency: value.currency };
  });
}

export function format(value: Money, locale = "en-IE"): string {
  const digits = MINOR_UNITS[value.currency];
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: value.currency,
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value.amount / 10 ** digits);
}

/** Parses text such as "1.234,50" or "1,234.50", taking the last separator as the decimal one. */
export function parse(text: string, currency: Currency): Money {
  const cleaned = text.replace(/[^\d.,-]/g, "");
  const lastSeparator = Math.max(cleaned.lastIndexOf("."), cleaned.lastIndexOf(","));
  const hasDecimals = lastSeparator >= 0 && cleaned.length - lastSeparator - 1 <= 2;
  const whole = (hasDecimals ? cleaned.slice(0, lastSeparator) : cleaned).replace(/[.,]/g, "");
  const fraction = hasDecimals ? cleaned.slice(lastSeparator + 1) : "0";
  const value = Number(`${whole || "0"}.${fraction}`);
  if (Number.isNaN(value)) throw new SyntaxError(`Not a price: ${text}`);
  return money(value, currency);
}

export interface PriceLine {
  label: string;
  net: Money;
  taxRate: number;
}

export function withTax(line: PriceLine): Money {
  return add(line.net, multiply(line.net, line.taxRate));
}

export function summarise(lines: PriceLine[]): { net: Money; tax: Money; gross: Money } {
  if (lines.length === 0) throw new RangeError("at least one line is required");
  const zero: Money = { amount: 0, currency: lines[0].net.currency };
  const net = lines.reduce((sum, line) => add(sum, line.net), zero);
  const gross = lines.reduce((sum, line) => add(sum, withTax(line)), zero);
  return { net, tax: subtract(gross, net), gross };
}

export function discountPercent(original: Money, reduced: Money): number {
  sameCurrency(original, reduced);
  if (original.amount === 0) return 0;
  return Math.round(((original.amount - reduced.amount) / original.amount) * 1000) / 10;
}

export function cheapest(prices: Money[]): Money | undefined {
  return prices.reduce<Money | undefined>((best, price) => {
    if (best) sameCurrency(best, price);
    return !best || price.amount < best.amount ? price : best;
  }, undefined);
}
