import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 개발 서버는 /api/* 요청을 FastAPI(127.0.0.1:8000)로 프록시한다.
// (백엔드에 CORS 설정을 추가하지 않아도 되도록 프록시 사용)
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
