/** รูปของเสียงในคลัง ไม่มีรูปแสดงพยัญชนะตัวแรกของชื่อ */
export default function VoiceAvatar({ name, url, size = 56 }: { name: string; url: string; size?: number }) {
  return url ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img className="avatar" src={url} alt="" width={size} height={size} style={{ width: size, height: size }} />
  ) : (
    <span className="avatar" style={{ width: size, height: size, fontSize: size * 0.4 }} aria-hidden="true">
      {name.trim().replace(/^[เแโใไ]/, "").charAt(0) || "?"}
    </span>
  );
}
