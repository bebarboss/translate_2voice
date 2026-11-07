import Link from "next/link";

export const BRAND_NAME = "Pakdee";
export const BRAND_TAGLINE = "พากย์ดี · AI พากย์ไทย";

/** ไอคอนนกแก้ว Pakdee จากโลโก้ต้นฉบับ */
export function BrandMark({ size = 34, className = "brand-mark" }: { size?: number; className?: string }) {
  return (
    <span className={className} style={{ width: size, height: size }}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/brand/icon.png"
        srcSet="/brand/icon.png 1x, /brand/icon-2x.png 2x, /brand/icon-4x.png 4x"
        alt=""
        width={size}
        height={size}
      />
    </span>
  );
}

function BrandLabel({ subtitle }: { subtitle?: string }) {
  return subtitle
    ? <span className="auth-brand-text">{BRAND_NAME}<small>{subtitle}</small></span>
    : <>{BRAND_NAME}</>;
}

/** ไอคอน + ชื่อ (ไม่ใช่ลิงก์) */
export function BrandLockup({
  subtitle,
  className = "brand",
  markSize = 34,
  markClassName,
}: {
  subtitle?: string;
  className?: string;
  markSize?: number;
  markClassName?: string;
}) {
  return (
    <div className={className}>
      <BrandMark size={markSize} className={markClassName ?? "brand-mark"} />
      <BrandLabel subtitle={subtitle} />
    </div>
  );
}

/** ลิงก์แบรนด์: ไอคอน + ชื่อ (+ คำโปรยถ้ามี) */
export function BrandLink({
  href = "/dashboard",
  subtitle,
  className = "brand",
  markSize = 34,
  markClassName,
}: {
  href?: string;
  subtitle?: string;
  className?: string;
  markSize?: number;
  markClassName?: string;
}) {
  return (
    <Link href={href} className={className}>
      <BrandMark size={markSize} className={markClassName ?? "brand-mark"} />
      <BrandLabel subtitle={subtitle} />
    </Link>
  );
}
