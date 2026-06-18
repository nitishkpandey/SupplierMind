/**
 * Interactive map showing suppliers as pins with radius circle.
 * Uses Leaflet + OpenStreetMap tiles (both free, no API key needed).
 */

import { useEffect, useRef } from "react";
import type { QueryResult, ParsedConstraints } from "@/types";
import type { Map } from "leaflet";
import { formatSupplierLocation } from "./location";

import "leaflet/dist/leaflet.css";

interface SupplierMapProps {
  results: QueryResult[];
  constraints?: ParsedConstraints | null;
}

export function SupplierMap({ results, constraints }: SupplierMapProps) {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<Map | null>(null);

  useEffect(() => {
    if (!mapRef.current || mapInstanceRef.current) return;

    import("leaflet").then((L) => {
      // Fix default marker icons (Leaflet + bundler path issue)
      delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl;
      L.Icon.Default.mergeOptions({
        iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
        iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
        shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
      });

      const centerLat = constraints?.location_lat ?? 51.1657;
      const centerLng = constraints?.location_lng ?? 10.4515;
      const zoom = constraints?.location_radius_km ? 9 : 6;

      const map = L.map(mapRef.current!).setView([centerLat, centerLng], zoom);
      mapInstanceRef.current = map;

      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19,
      }).addTo(map);

      // Radius circle + search-center pin
      if (constraints?.location_lat && constraints?.location_lng && constraints?.location_radius_km) {
        L.circle([constraints.location_lat, constraints.location_lng], {
          radius: constraints.location_radius_km * 1000,
          color: "#3b82f6",
          fillColor: "#3b82f6",
          fillOpacity: 0.08,
          weight: 2,
        }).addTo(map);

        L.circleMarker([constraints.location_lat, constraints.location_lng], {
          radius: 6,
          color: "#3b82f6",
          fillColor: "#3b82f6",
          fillOpacity: 1,
        })
          .addTo(map)
          .bindPopup(`<b>Search centre</b><br>${constraints.location_name ?? ""}`);
      }

      // Supplier pins — ranked by score; rank #1 gets a different colour
      results.forEach((result) => {
        const lat = result.supplier_lat;
        const lng = result.supplier_lng;
        if (lat == null || lng == null) return;

        const isTop = result.rank === 1;
        const color = isTop ? "#f59e0b" : "#3b82f6";

        const marker = L.circleMarker([lat, lng], {
          radius: isTop ? 10 : 8,
          color,
          fillColor: color,
          fillOpacity: 0.85,
          weight: 2,
        }).addTo(map);

        const scoreLabel = `${Math.round(result.total_score * 100)}%`;
        const name = result.supplier_name ?? result.supplier_id.slice(0, 8);
        const location = formatSupplierLocation(
          result.supplier_city,
          result.supplier_country,
        ) ?? "Location not verified";

        marker.bindPopup(
          `<b>#${result.rank} ${name}</b><br>${location}<br>Match: <b>${scoreLabel}</b>`
        );
      });
    });

    return () => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      ref={mapRef}
      className="w-full h-80 rounded-xl border overflow-hidden bg-muted"
      style={{ zIndex: 0 }}
    />
  );
}
