var _a;
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
var target = (_a = process.env.LLAMA_SERVER_URL) !== null && _a !== void 0 ? _a : "http://192.168.0.64:8080";
export default defineConfig({
    plugins: [react()],
    server: {
        host: "0.0.0.0",
        port: 5173,
        proxy: {
            "/api": {
                target: target,
                changeOrigin: true,
                rewrite: function (path) { return path.replace(/^\/api/, ""); },
            },
            "/rag": {
                target: "http://192.168.0.64:8082",
                changeOrigin: true,
                rewrite: function (path) { return path.replace(/^\/rag/, ""); },
            },
            "/manager": {
                target: "http://192.168.0.64:8081",
                changeOrigin: true,
                rewrite: function (path) { return path.replace(/^\/manager/, ""); },
            },
        },
    },
});
