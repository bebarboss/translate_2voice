import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // ไฟล์วิดีโอสตรีมผ่าน /api ไม่ต้องบีบอัดซ้ำ
  compress: false,
  // image เล็กสำหรับ deploy VPS (deploy/frontend.Dockerfile)
  output: "standalone",
};

export default nextConfig;
