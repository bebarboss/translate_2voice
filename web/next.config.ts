import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // ไฟล์วิดีโอสตรีมผ่าน /api ไม่ต้องบีบอัดซ้ำ
  compress: false,
};

export default nextConfig;
