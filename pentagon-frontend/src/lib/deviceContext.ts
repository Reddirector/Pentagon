/**
 * Device, GPS & Environmental Context Service for Pentagon
 * Collects real-time client factors:
 * - High-accuracy GPS coordinates & reverse-geocoded location
 * - Timezone, local user clock & UTC offset
 * - Device platform (Linux, macOS, Windows, iOS, Android), screen resolution, & locale
 */

export interface UserLocation {
  latitude: number
  longitude: number
  accuracy_m?: number
  city?: string
  region?: string
  country?: string
  label?: string
  source: 'gps' | 'ip' | 'browser'
  updated_at: string
}

export interface ClientEnvironmentContext {
  timezone: string
  local_time: string
  utc_offset: string
  platform: string
  screen: {
    width: number
    height: number
    devicePixelRatio: number
  }
  language: string
  color_scheme: 'dark' | 'light'
  location: UserLocation | null
}

const LOCATION_STORAGE_KEY = 'pentagon.user_location'

export function getCachedLocation(): UserLocation | null {
  try {
    const raw = localStorage.getItem(LOCATION_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as UserLocation
    if (parsed && typeof parsed.latitude === 'number' && typeof parsed.longitude === 'number') {
      return parsed
    }
  } catch {
    // ignore
  }
  return null
}

export function clearLocation(): void {
  try {
    localStorage.removeItem(LOCATION_STORAGE_KEY)
  } catch {
    // ignore
  }
}

export async function reverseGeocodeCoordinates(
  lat: number,
  lon: number
): Promise<{ city?: string; region?: string; country?: string; label?: string }> {
  try {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 3500)
    const res = await fetch(
      `https://api.bigdatacloud.net/data/reverse-geocode-client?latitude=${lat}&longitude=${lon}&localityLanguage=en`,
      { signal: controller.signal }
    )
    clearTimeout(timeout)
    if (res.ok) {
      const data = (await res.json()) as {
        city?: string
        locality?: string
        principalSubdivision?: string
        countryName?: string
      }
      const city = data.city || data.locality || ''
      const region = data.principalSubdivision || ''
      const country = data.countryName || ''

      const labelParts = [city, region || country].filter(Boolean)
      const label = labelParts.length > 0 ? labelParts.join(', ') : `${lat.toFixed(4)}°, ${lon.toFixed(4)}°`

      return { city, region, country, label }
    }
  } catch {
    // ignore lookup error
  }
  return { label: `${lat.toFixed(4)}°, ${lon.toFixed(4)}°` }
}

export async function requestGpsLocation(enableHighAccuracy = true): Promise<UserLocation | null> {
  if (typeof navigator === 'undefined' || !navigator.geolocation) {
    return null
  }

  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const lat = pos.coords.latitude
        const lon = pos.coords.longitude
        const accuracy = Math.round(pos.coords.accuracy)

        const geo = await reverseGeocodeCoordinates(lat, lon)
        const location: UserLocation = {
          latitude: lat,
          longitude: lon,
          accuracy_m: accuracy,
          city: geo.city,
          region: geo.region,
          country: geo.country,
          label: geo.label,
          source: 'gps',
          updated_at: new Date().toISOString(),
        }

        try {
          localStorage.setItem(LOCATION_STORAGE_KEY, JSON.stringify(location))
        } catch {
          // ignore
        }
        resolve(location)
      },
      () => {
        resolve(null)
      },
      {
        enableHighAccuracy,
        timeout: 10000,
        maximumAge: 120000,
      }
    )
  })
}

export function getPlatformDescription(): string {
  if (typeof window === 'undefined') return 'Server'
  const nav = navigator as unknown as { userAgentData?: { platform?: string } }
  const ua = navigator.userAgent || ''

  if (/Android/i.test(ua)) return 'Android'
  if (/iPhone|iPad|iPod/i.test(ua)) return 'iOS'
  if (/Mac/i.test(ua) || nav.userAgentData?.platform === 'macOS') return 'macOS'
  if (/Win/i.test(ua) || nav.userAgentData?.platform === 'Windows') return 'Windows'
  if (/Linux/i.test(ua) || nav.userAgentData?.platform === 'Linux') return 'Linux'
  return navigator.platform || 'Desktop'
}

export function getUtcOffsetString(): string {
  const offsetMinutes = -new Date().getTimezoneOffset()
  const sign = offsetMinutes >= 0 ? '+' : '-'
  const absMinutes = Math.abs(offsetMinutes)
  const hours = String(Math.floor(absMinutes / 60)).padStart(2, '0')
  const minutes = String(absMinutes % 60).padStart(2, '0')
  return `${sign}${hours}:${minutes}`
}

export function getClientEnvironmentContext(): ClientEnvironmentContext {
  const now = new Date()
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  const formattedLocalTime = now.toLocaleString('en-US', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  })

  return {
    timezone,
    local_time: `${formattedLocalTime} (${timezone}, UTC${getUtcOffsetString()})`,
    utc_offset: getUtcOffsetString(),
    platform: getPlatformDescription(),
    screen: {
      width: typeof window !== 'undefined' ? window.innerWidth : 1920,
      height: typeof window !== 'undefined' ? window.innerHeight : 1080,
      devicePixelRatio: typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1,
    },
    language: typeof navigator !== 'undefined' ? navigator.language : 'en-US',
    color_scheme:
      typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches
        ? 'dark'
        : 'light',
    location: getCachedLocation(),
  }
}
