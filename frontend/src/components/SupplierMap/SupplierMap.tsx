/**
 * Interactive map showing suppliers as pins with radius circle.
 * Uses Leaflet + OpenStreetMap tiles (both free, no API key needed).
 */

import { useEffect, useRef } from "react";
import type { QueryResult, ParsedConstraints } from "@/types";

// Import Leaflet CSS
import "leaflet/dist/leaflet.css";

interface SupplierMapProps {
  results: QueryResult[];
  constraints?: ParsedConstraints | null;
}

export function SupplierMap({ results: _, constraints }: SupplierMapProps) {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<any>(null);

  useEffect(() => {
    if (!mapRef.current || mapInstanceRef.current) return;

    // Dynamic import to avoid SSR issues
    import("leaflet").then((L) => {
      // Fix default marker icons (Leaflet + bundler issue)
      delete (L.Icon.Default.prototype as any)._getIconUrl;
      L.Icon.Default.mergeOptions({
        iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
        iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
        shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
      });

      const centerLat = constraints?.location_lat ?? 51.1657;
      const centerLng = constraints?.location_lng ?? 10.4515;
      const zoom = constraints?.location_radius_km ? 10 : 5;

      const map = L.map(mapRef.current!).setView([centerLat, centerLng], zoom);
      mapInstanceRef.current = map;

      // OpenStreetMap tiles (free, no API key)
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19,
      }).addTo(map);

      // Radius circle
      if (constraints?.location_lat && constraints?.location_lng && constraints?.location_radius_km) {
        L.circle([constraints.location_lat, constraints.location_lng], {
          radius: constraints.location_radius_km * 1000, // convert km to meters
          color: "#3b82f6",
          fillColor: "#3b82f6",
          fillOpacity: 0.08,
          weight: 2,
        }).addTo(map);

        // Center marker
        L.circleMarker([constraints.location_lat, constraints.location_lng], {
          radius: 6,
          color: "#3b82f6",
          fillColor: "#3b82f6",
          fillOpacity: 1,
        })
          .addTo(map)
          .bindPopup(`<b>Search center</b><br>${constraints.location_name ?? ""}`);
      }
    });

    return () => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
    };
  }, []);

  return (
    <div
      ref={mapRef}
      className="w-full h-80 rounded-xl border overflow-hidden bg-muted"
      style={{ zIndex: 0 }}
    />
  );
}
