import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  build: {
    rolldownOptions: {
      output: {
        chunkFileNames: "assets/[name]-[hash].js",
        codeSplitting: {
          groups: [
            {
              name: "react-vendor",
              test: /node_modules[\\/](react|react-dom|react-router|react-router-dom)[\\/]/,
              priority: 40,
            },
            {
              name: "radix-ui",
              test: /node_modules[\\/]@radix-ui[\\/]/,
              priority: 35,
            },
            {
              name: "charts",
              test: /node_modules[\\/](recharts|d3-|victory-vendor)[\\/]/,
              priority: 30,
            },
            {
              name: "maps",
              test: /node_modules[\\/]leaflet[\\/]/,
              priority: 30,
            },
            {
              name: "data-vendor",
              test: /node_modules[\\/](@tanstack|axios|i18next|react-i18next|date-fns)[\\/]/,
              priority: 25,
            },
            {
              name: "ui-vendor",
              test: /node_modules[\\/](lucide-react|class-variance-authority|clsx|tailwind-merge|zustand)[\\/]/,
              priority: 20,
            },
            {
              name: "vendor",
              test: /node_modules[\\/]/,
              priority: 10,
              maxSize: 300 * 1024,
            },
          ],
        },
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Proxy API calls to avoid CORS in development
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
