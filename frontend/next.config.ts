import type { NextConfig } from "next";

// หัวตอบของหน้าที่เบราว์เซอร์เรนเดอร์ (DWT-195)
// HSTS, nosniff, Referrer-Policy ตั้งที่ Caddy แล้ว — อย่าซ้ำที่นี่
// CSP เป็น Report-Only ตามที่ IT สั่ง: ยังไม่บล็อก ดู violation ในคอนโซล
// ไม่ใส่ report-uri / report-to เพราะยังไม่มีตัวรับรายงาน

/** โดเมน API สาธารณะ (PUBLIC_BACKEND_URL) — เบราว์เซอร์อัปโหลดตรงเมื่อ DIRECT_UPLOAD=1 */
const API_ORIGIN = "https://pakdee-api.cobie.online";

function contentSecurityPolicy(): string {
  // Next dev ใช้ eval เพื่อประกอบ stack ฝั่งเซิร์ฟเวอร์ — production ไม่ใช้
  const dev = process.env.NODE_ENV === "development";
  const scriptSrc = [
    "'self'",
    // สคริปต์ inline ของ Next.js (bootstrap / hydration)
    "'unsafe-inline'",
    // Google Identity Services: https://accounts.google.com/gsi/client
    "https://accounts.google.com/gsi/client",
    // Stripe.js และ Checkout (ยังไม่ฝังสคริปต์ แต่ต้องเผื่อตาม DWT-195)
    // https://docs.stripe.com/security/guide#content-security-policy
    "https://js.stripe.com",
    "https://*.js.stripe.com",
    "https://checkout.stripe.com",
    ...(dev ? ["'unsafe-eval'"] : []),
  ];
  const connectSrc = [
    "'self'",
    API_ORIGIN,
    "https://accounts.google.com/gsi/",
    "https://api.stripe.com",
    "https://checkout.stripe.com",
    ...(dev ? ["http://localhost:8000", "http://127.0.0.1:8000"] : []),
  ];
  return [
    "default-src 'self'",
    `script-src ${scriptSrc.join(" ")}`,
    // style={{}} ทั้งแอป และสไตล์ของปุ่ม Google
    "style-src 'self' 'unsafe-inline' https://accounts.google.com/gsi/style",
    // รูปในเครื่อง, blob ตัวอย่างรูปเสียง, SVG data: ใน CSS, ไอคอนของ Stripe
    "img-src 'self' blob: data: https://*.stripe.com",
    // IBM Plex ผ่าน @fontsource อยู่ใต้ /_next/static — ไม่ได้โหลด Google Fonts
    "font-src 'self'",
    `connect-src ${connectSrc.join(" ")}`,
    "frame-src https://accounts.google.com/gsi/ https://js.stripe.com https://*.js.stripe.com https://hooks.stripe.com https://checkout.stripe.com",
    // วิดีโอ/เสียงผ่าน /api และไฟล์ใน /brand; blob: คือพรีวิวไฟล์ในเครื่องและเสียงที่อัดจากไมค์
    "media-src 'self' blob:",
    "worker-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self' https://checkout.stripe.com",
    "frame-ancestors 'none'",
    // ตอนเป็น Report-Only เบราว์เซอร์ไม่ทำ upgrade — พร้อมไว้ตอนเปลี่ยนเป็นบังคับจริง
    "upgrade-insecure-requests",
  ].join("; ");
}

// ปิดของที่ไม่ได้ใช้ เปิดเฉพาะที่แอปเรียกจริง
// ไมค์: components/Recorder.tsx (getUserMedia เฉพาะเสียง)
// autoplay: คลิปสมัครนักพากย์ใน /welcome (autoPlay muted)
// fullscreen / picture-in-picture: ปุ่มของ <video controls>
// clipboard-write: คัดลอกเลขบัญชีและบท
const permissionsPolicy = [
  "accelerometer=()",
  "autoplay=(self)",
  "bluetooth=()",
  "camera=()",
  "clipboard-read=()",
  "clipboard-write=(self)",
  "display-capture=()",
  "encrypted-media=()",
  "fullscreen=(self)",
  "geolocation=()",
  "gyroscope=()",
  "magnetometer=()",
  "microphone=(self)",
  "midi=()",
  "payment=()",
  "picture-in-picture=(self)",
  "usb=()",
].join(", ");

const securityHeaders = [
  { key: "Content-Security-Policy-Report-Only", value: contentSecurityPolicy() },
  // บังคับจริงวันนี้ — frame-ancestors ใน CSP ยังเป็น Report-Only จึงยังไม่กันการฝังเฟรม
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: permissionsPolicy },
];

const nextConfig: NextConfig = {
  // ไฟล์วิดีโอสตรีมผ่าน /api ไม่ต้องบีบอัดซ้ำ
  compress: false,
  // image เล็กสำหรับ deploy VPS (deploy/frontend.Dockerfile)
  output: "standalone",
  poweredByHeader: false,
  headers() {
    // /(.*) จับ "/" ด้วย (ตรวจกับ Next 16.4.3 แล้ว — หัวไม่ซ้ำ)
    return [{ source: "/(.*)", headers: securityHeaders }];
  },
};

export default nextConfig;
