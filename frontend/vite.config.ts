import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";

const target = process.env.LLAMA_SERVER_URL ?? "http://192.168.0.64:8080";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
      "/rag": {
        target: "http://192.168.0.64:8082",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/rag/, ""),
      },
      "/manager": {
        target: "http://192.168.0.64:8081",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/manager/, ""),
      },
    },
  },
});
