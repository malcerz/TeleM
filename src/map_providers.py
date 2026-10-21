"""Central registry and capabilities contract for map tile providers in SportCamHUD.

Enforces provider licensing, rate limiting, prefetch restrictions, cache expiry,
and video export permissions before actions are taken.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


class ExportPermission:
    CONFIRMED = "confirmed"
    CONDITIONAL = "conditional"
    PROHIBITED = "prohibited"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MapProviderCapabilities:
    """Legal and technical capability descriptor for a map tile provider."""
    provider_id: str
    name: str
    service_url: str
    attribution_text: str
    attribution_url: str
    requires_api_key: bool
    supports_live_tiles: bool
    allows_route_prefetch: bool
    allows_offline_cache: bool
    cache_max_age: Optional[int]  # in days; None = indefinite / user-controlled
    requires_visible_attribution: bool
    video_export_permission: str  # confirmed | conditional | prohibited | unknown
    commercial_use_permission: str  # confirmed | conditional | prohibited | unknown
    terms_url: str
    notes: str = ""

    @property
    def cache_max_age_days(self) -> Optional[int]:
        """Alias for cache_max_age in days."""
        return self.cache_max_age


# URL pattern to mask sensitive keys in logs
_KEY_MASK_REGEX = re.compile(r"([?&](?:api_key|token|key)=)[^&]+", re.IGNORECASE)


def mask_url(url: str) -> str:
    """Mask sensitive tokens or API keys in URL strings for safe logging."""
    if not url:
        return ""
    return _KEY_MASK_REGEX.sub(r"\1***", url)


# Built-in Provider Definitions
_BUILTIN_PROVIDERS: dict[str, MapProviderCapabilities] = {
    "osm": MapProviderCapabilities(
        provider_id="osm",
        name="OpenStreetMap Standard",
        service_url="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        attribution_text="© OpenStreetMap contributors",
        attribution_url="https://www.openstreetmap.org/copyright",
        requires_api_key=False,
        supports_live_tiles=True,
        allows_route_prefetch=False,  # OSMF Tile Usage Policy strictly forbids bulk prefetch / scraping
        allows_offline_cache=True,
        cache_max_age=7,  # Min 7 days default if unheaded; obey HTTP caching headers
        requires_visible_attribution=True,
        video_export_permission=ExportPermission.CONDITIONAL,
        commercial_use_permission=ExportPermission.CONDITIONAL,
        terms_url="https://operations.osmfoundation.org/policies/tiles/",
        notes=(
            "Serwer kafelkow OSMF zabrania masowego pobierania/prefetchu trasy. "
            "Dozwolone wylacznie pobieranie live na biezaco wyswietlanych kafelkow. "
            "Do eksportu dlugich tras MP4 zalecany wlasny serwer kafelkow lub wczesniejszy cache."
        ),
    ),
    "light_all": MapProviderCapabilities(
        provider_id="light_all",
        name="CARTO Positron (Light All)",
        service_url="https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
        attribution_text="© OpenStreetMap contributors, © CARTO",
        attribution_url="https://carto.com/attribution/",
        requires_api_key=True,  # CARTO Basemaps require user API key for official access
        supports_live_tiles=True,
        allows_route_prefetch=False,  # Bulk harvesting outside direct app views prohibited
        allows_offline_cache=True,
        cache_max_age=30,  # CARTO explicitly restricts client cache to max 30 days
        requires_visible_attribution=True,
        video_export_permission=ExportPermission.CONDITIONAL,
        commercial_use_permission=ExportPermission.CONDITIONAL,
        terms_url="https://carto.com/legal/basemap-terms/",
        notes=(
            "Wymagany klucz API CARTO. Darmowy limit komercyjny: 1M requestow/mies., "
            "niekomercyjny: 5M requestow/mies. Maksymalny czas cache na urzadzeniu: 30 dni. "
            "Wymagana widoczna atrybucja na mapie."
        ),
    ),
    "light_nolabels": MapProviderCapabilities(
        provider_id="light_nolabels",
        name="CARTO Positron (No Labels)",
        service_url="https://a.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png",
        attribution_text="© OpenStreetMap contributors, © CARTO",
        attribution_url="https://carto.com/attribution/",
        requires_api_key=True,
        supports_live_tiles=True,
        allows_route_prefetch=False,
        allows_offline_cache=True,
        cache_max_age=30,
        requires_visible_attribution=True,
        video_export_permission=ExportPermission.CONDITIONAL,
        commercial_use_permission=ExportPermission.CONDITIONAL,
        terms_url="https://carto.com/legal/basemap-terms/",
        notes="Wymagany klucz API CARTO. Maksymalny cache 30 dni. Wymagana atrybucja.",
    ),
    "dark_all": MapProviderCapabilities(
        provider_id="dark_all",
        name="CARTO Dark Matter (Dark All)",
        service_url="https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        attribution_text="© OpenStreetMap contributors, © CARTO",
        attribution_url="https://carto.com/attribution/",
        requires_api_key=True,
        supports_live_tiles=True,
        allows_route_prefetch=False,
        allows_offline_cache=True,
        cache_max_age=30,
        requires_visible_attribution=True,
        video_export_permission=ExportPermission.CONDITIONAL,
        commercial_use_permission=ExportPermission.CONDITIONAL,
        terms_url="https://carto.com/legal/basemap-terms/",
        notes="Wymagany klucz API CARTO. Maksymalny cache 30 dni. Wymagana atrybucja.",
    ),
    "dark_nolabels": MapProviderCapabilities(
        provider_id="dark_nolabels",
        name="CARTO Dark Matter (No Labels)",
        service_url="https://a.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}.png",
        attribution_text="© OpenStreetMap contributors, © CARTO",
        attribution_url="https://carto.com/attribution/",
        requires_api_key=True,
        supports_live_tiles=True,
        allows_route_prefetch=False,
        allows_offline_cache=True,
        cache_max_age=30,
        requires_visible_attribution=True,
        video_export_permission=ExportPermission.CONDITIONAL,
        commercial_use_permission=ExportPermission.CONDITIONAL,
        terms_url="https://carto.com/legal/basemap-terms/",
        notes="Wymagany klucz API CARTO. Maksymalny cache 30 dni. Wymagana atrybucja.",
    ),
    "voyager_all": MapProviderCapabilities(
        provider_id="voyager_all",
        name="CARTO Voyager (All Labels)",
        service_url="https://a.basemaps.cartocdn.com/voyager_all/{z}/{x}/{y}.png",
        attribution_text="© OpenStreetMap contributors, © CARTO",
        attribution_url="https://carto.com/attribution/",
        requires_api_key=True,
        supports_live_tiles=True,
        allows_route_prefetch=False,
        allows_offline_cache=True,
        cache_max_age=30,
        requires_visible_attribution=True,
        video_export_permission=ExportPermission.CONDITIONAL,
        commercial_use_permission=ExportPermission.CONDITIONAL,
        terms_url="https://carto.com/legal/basemap-terms/",
        notes="Wymagany klucz API CARTO. Maksymalny cache 30 dni. Wymagana atrybucja.",
    ),
    "voyager_nolabels": MapProviderCapabilities(
        provider_id="voyager_nolabels",
        name="CARTO Voyager (No Labels)",
        service_url="https://a.basemaps.cartocdn.com/voyager_nolabels/{z}/{x}/{y}.png",
        attribution_text="© OpenStreetMap contributors, © CARTO",
        attribution_url="https://carto.com/attribution/",
        requires_api_key=True,
        supports_live_tiles=True,
        allows_route_prefetch=False,
        allows_offline_cache=True,
        cache_max_age=30,
        requires_visible_attribution=True,
        video_export_permission=ExportPermission.CONDITIONAL,
        commercial_use_permission=ExportPermission.CONDITIONAL,
        terms_url="https://carto.com/legal/basemap-terms/",
        notes="Wymagany klucz API CARTO. Maksymalny cache 30 dni. Wymagana atrybucja.",
    ),
    "satellite": MapProviderCapabilities(
        provider_id="satellite",
        name="Esri World Imagery (Satellite)",
        service_url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attribution_text="Sources: Esri, Maxar, Earthstar Geographics, and the GIS User Community",
        attribution_url="https://www.esri.com/en-us/legal/copyright-trademarks",
        requires_api_key=True,
        supports_live_tiles=True,
        allows_route_prefetch=False,  # Unauthenticated public endpoint does not allow bulk scraping
        allows_offline_cache=False,  # Offline export restricted to tiledbasemaps export-enabled service
        cache_max_age=30,
        requires_visible_attribution=True,
        video_export_permission=ExportPermission.CONDITIONAL,  # Private use only; monetized video requires commercial license
        commercial_use_permission=ExportPermission.PROHIBITED,  # Prohibited without paid ArcGIS commercial license
        terms_url="https://developers.arcgis.com/documentation/mapping-and-location-services/mapping/basemaps/introduction-static-basemap-tiles-service/",
        notes=(
            "ArcGIS World Imagery na publicznym punkcie server.arcgisonline.com nie daje potwierdzonego prawa "
            "do komercyjnego eksportu wideo i monetyzacji na YouTube bez licencji komercyjnej Esri oraz pelnej atrybucji."
        ),
    ),
    "custom": MapProviderCapabilities(
        provider_id="custom",
        name="Custom / Self-Hosted Tile Server",
        service_url="http://localhost:8080/styles/basic/{z}/{x}/{y}.png",
        attribution_text="",
        attribution_url="",
        requires_api_key=False,
        supports_live_tiles=True,
        allows_route_prefetch=True,  # Full prefetch permitted on user's own server
        allows_offline_cache=True,
        cache_max_age=None,  # User controlled
        requires_visible_attribution=False,  # Depends on user's base data
        video_export_permission=ExportPermission.CONFIRMED,
        commercial_use_permission=ExportPermission.CONFIRMED,
        terms_url="",
        notes="Wlasne zrodlo kafelkow (np. TileServer GL / lokalny mbtiles). Pelna swoboda uzytkowania i prefetchu.",
    ),
}

# Style alias mapping to canonical provider IDs
_STYLE_ALIASES: dict[str, str] = {
    "carto_light_all": "light_all",
    "carto_light_nolabels": "light_nolabels",
    "carto_dark_all": "dark_all",
    "carto_dark_nolabels": "dark_nolabels",
    "carto_voyager_all": "voyager_all",
    "carto_voyager_nolabels": "voyager_nolabels",
    "esri_satellite": "satellite",
    "arcgis_satellite": "satellite",
    "self_hosted": "custom",
    "local": "custom",
}


class MapProviderRegistry:
    """Registry managing map provider capabilities, URL formatting, and permission pre-checks."""

    _custom_providers: dict[str, MapProviderCapabilities] = {}

    @classmethod
    def register_provider(cls, capabilities: MapProviderCapabilities) -> None:
        """Register or override a map provider capability profile."""
        cls._custom_providers[capabilities.provider_id.lower()] = capabilities

    @classmethod
    def resolve_provider_id(cls, style_or_id: str) -> str:
        """Resolve a style string or alias to a canonical provider ID."""
        key = str(style_or_id or "light_all").strip().lower()
        return _STYLE_ALIASES.get(key, key)

    @classmethod
    def get_capabilities(cls, style_or_id: str) -> MapProviderCapabilities:
        """Return capabilities for a provider, falling back to a safe default if unknown."""
        key = str(style_or_id or "light_all").strip()
        canonical = cls.resolve_provider_id(key)

        # 1. Registered custom provider
        if canonical in cls._custom_providers:
            return cls._custom_providers[canonical]

        # 2. Builtin provider
        if canonical in _BUILTIN_PROVIDERS:
            return _BUILTIN_PROVIDERS[canonical]

        # 3. Direct URL template passed as style
        if key.startswith("http://") or key.startswith("https://"):
            return MapProviderCapabilities(
                provider_id="custom_url",
                name=f"Custom URL ({mask_url(key)[:40]}...)",
                service_url=key,
                attribution_text="",
                attribution_url="",
                requires_api_key=False,
                supports_live_tiles=True,
                allows_route_prefetch=True,
                allows_offline_cache=True,
                cache_max_age=None,
                requires_visible_attribution=False,
                video_export_permission=ExportPermission.CONFIRMED,
                commercial_use_permission=ExportPermission.CONFIRMED,
                terms_url="",
                notes="Zrodlo zdefiniowane przez uzytkownika jako URL template.",
            )

        # 4. Unknown provider - safe defensive fallback (unknown != confirmed!)
        return MapProviderCapabilities(
            provider_id=canonical,
            name=f"Unknown Provider ({canonical})",
            service_url="",
            attribution_text="",
            attribution_url="",
            requires_api_key=False,
            supports_live_tiles=False,
            allows_route_prefetch=False,
            allows_offline_cache=False,
            cache_max_age=0,
            requires_visible_attribution=True,
            video_export_permission=ExportPermission.UNKNOWN,
            commercial_use_permission=ExportPermission.UNKNOWN,
            terms_url="",
            notes="Nieznany dostawca. Wymaga weryfikacji przed uzyciem.",
        )

    @classmethod
    def can_prefetch(cls, style_or_id: str) -> bool:
        """Check whether bulk route prefetch is permitted for this provider."""
        caps = cls.get_capabilities(style_or_id)
        return caps.allows_route_prefetch

    @classmethod
    def can_export_video(
        cls,
        style_or_id: str,
        is_commercial: bool = False,
    ) -> tuple[str, str]:
        """Check video export permissions.

        Returns:
            (permission_status, explanation)
            where permission_status is confirmed | conditional | prohibited | unknown
        """
        caps = cls.get_capabilities(style_or_id)
        perm = caps.commercial_use_permission if is_commercial else caps.video_export_permission

        if perm == ExportPermission.CONFIRMED:
            return perm, f"Eksport wideo jest w pelni potwierdzony dla dostawcy {caps.name}."
        if perm == ExportPermission.PROHIBITED:
            return perm, f"Eksport wideo jest zabroniony dla dostawcy {caps.name} na obecnych warunkach."
        if perm == ExportPermission.CONDITIONAL:
            reasons = []
            if caps.requires_api_key:
                reasons.append("wymaga zarejestrowanego klucza API")
            if caps.requires_visible_attribution:
                reasons.append(f"wymaga atrybucji: '{caps.attribution_text}'")
            if not caps.allows_route_prefetch:
                reasons.append("zabrania masowego prefetchu trasy (dozwolone pobieranie na zywo)")
            detail = "; ".join(reasons) if reasons else "wymaga spelnienia warunkow licencyjnych"
            return perm, f"Eksport wideo dla {caps.name} jest warunkowy ({detail})."
        return ExportPermission.UNKNOWN, f"Status prawny eksportu dla {caps.name} nie jest potwierdzony."

    @classmethod
    def get_attribution(cls, style_or_id: str) -> tuple[str, str]:
        """Return (attribution_text, attribution_url) for the provider."""
        caps = cls.get_capabilities(style_or_id)
        return caps.attribution_text, caps.attribution_url

    @classmethod
    def format_tile_url(
        cls,
        style_or_id: str,
        z: int,
        x: int,
        y: int,
        api_key: Optional[str] = None,
    ) -> str:
        """Format the full tile URL including coordinate substitution and safe API key injection."""
        caps = cls.get_capabilities(style_or_id)
        url = caps.service_url
        if not url:
            return ""

        # Fetch API key from credential store if not explicitly supplied
        if api_key is None and caps.requires_api_key:
            try:
                from src.integrations.credential_store import get_map_api_key
                api_key = get_map_api_key(caps.provider_id)
                if not api_key:
                    if "cartocdn.com" in url or "carto" in caps.provider_id or caps.provider_id.startswith(("light_", "dark_", "voyager_")):
                        api_key = get_map_api_key("carto")
                    elif "arcgisonline.com" in url or "satellite" in caps.provider_id:
                        api_key = get_map_api_key("esri") or get_map_api_key("arcgis")
            except Exception:
                api_key = None

        # ArcGIS uses row/column order {z}/{y}/{x} in default template; standard OSM uses {z}/{x}/{y}
        formatted = url.format(z=z, x=x, y=y, style=caps.provider_id)

        # Inject API key according to provider standard
        if api_key:
            key_str = str(api_key).strip()
            if "{apiKey}" in formatted:
                formatted = formatted.replace("{apiKey}", key_str)
            elif "{token}" in formatted:
                formatted = formatted.replace("{token}", key_str)
            elif "cartocdn.com" in formatted:
                sep = "&" if "?" in formatted else "?"
                formatted = f"{formatted}{sep}api_key={key_str}"
            elif "arcgisonline.com" in formatted:
                sep = "&" if "?" in formatted else "?"
                formatted = f"{formatted}{sep}token={key_str}"

        return formatted

    @classmethod
    def all_providers(cls) -> list[MapProviderCapabilities]:
        """List all known providers."""
        return list(_BUILTIN_PROVIDERS.values()) + list(cls._custom_providers.values())


# Compatibility mapping matching legacy MAP_STYLES dictionaries
MAP_STYLES: dict[str, str] = {
    p.provider_id: p.service_url for p in _BUILTIN_PROVIDERS.values() if p.service_url
}
