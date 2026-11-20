// A typed client for a weather service, with caching and retry on transient errors.

export interface Coordinates {
  latitude: number;
  longitude: number;
}

export interface Forecast {
  time: string;
  temperatureC: number;
  windKph: number;
  precipitationMm: number;
  summary: string;
}

interface CacheEntry {
  expires: number;
  forecasts: Forecast[];
}

export class WeatherError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "WeatherError";
  }
}

const RETRYABLE = new Set([408, 429, 500, 502, 503, 504]);

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export class WeatherClient {
  private readonly cache = new Map<string, CacheEntry>();

  constructor(
    private readonly baseUrl: string,
    private readonly ttlMs = 10 * 60 * 1000,
    private readonly maxRetries = 3,
  ) {}

  private key(place: Coordinates, days: number): string {
    return `${place.latitude.toFixed(2)},${place.longitude.toFixed(2)}:${days}`;
  }

  async forecast(place: Coordinates, days = 3): Promise<Forecast[]> {
    if (days < 1 || days > 14) throw new RangeError("days must be between 1 and 14");
    const key = this.key(place, days);
    const cached = this.cache.get(key);
    if (cached && cached.expires > Date.now()) return cached.forecasts;

    const url = new URL("/v1/forecast", this.baseUrl);
    url.searchParams.set("lat", String(place.latitude));
    url.searchParams.set("lon", String(place.longitude));
    url.searchParams.set("days", String(days));

    const forecasts = await this.fetchWithRetry(url);
    this.cache.set(key, { expires: Date.now() + this.ttlMs, forecasts });
    return forecasts;
  }

  private async fetchWithRetry(url: URL): Promise<Forecast[]> {
    let lastError: unknown;
    for (let attempt = 0; attempt <= this.maxRetries; attempt += 1) {
      try {
        const response = await fetch(url, { headers: { Accept: "application/json" } });
        if (response.ok) return (await response.json()) as Forecast[];
        if (!RETRYABLE.has(response.status)) {
          throw new WeatherError(`Request failed with status ${response.status}`, response.status);
        }
        lastError = new WeatherError("Temporary failure", response.status);
      } catch (error) {
        if (error instanceof WeatherError && error.status && !RETRYABLE.has(error.status)) {
          throw error;
        }
        lastError = error;
      }
      await sleep(2 ** attempt * 250);
    }
    throw lastError instanceof Error ? lastError : new WeatherError("Request failed");
  }

  clearCache(): void {
    this.cache.clear();
  }
}

export function warmestDay(forecasts: Forecast[]): Forecast | undefined {
  return forecasts.reduce<Forecast | undefined>(
    (best, current) => (!best || current.temperatureC > best.temperatureC ? current : best),
    undefined,
  );
}

export function needsUmbrella(forecasts: Forecast[], thresholdMm = 1): boolean {
  return forecasts.some((forecast) => forecast.precipitationMm >= thresholdMm);
}
